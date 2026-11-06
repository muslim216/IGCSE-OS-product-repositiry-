"""T-027: the PDF library runs only in the sandbox's child process.

Two guards, because each misses what the other catches. The static one reads
every module's source, so it fails on an import nobody exercises yet. The
runtime one starts a fresh interpreter, imports the whole app and every job
handler, then reads and splits a booklet through the real job handlers
(`extract_booklet` and `split_booklet`, with the AI faked), so it fails on an
import made indirectly, by a dependency or at call time, that no source scan
would see. It has to be a fresh interpreter:
this test process imports the library itself to build its fixtures.
"""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from tests.test_booklets import _pdf

BACKEND = Path(__file__).resolve().parent.parent
#: The only two modules allowed to touch the library: the functions themselves,
#: and the child process that calls them.
ALLOWED = {
    BACKEND / "app" / "services" / "pdf.py",
    BACKEND / "app" / "services" / "pdf_child.py",
}
SCANNED = ("app", "seed")

_LIBRARY = re.compile(r"^pypdf(\.|$)")
_PDF_MODULE = re.compile(r"^app\.services\.pdf(\.|$)")
#: A module name as a quoted string, as `importlib.import_module` or
#: `__import__` would be handed it.
_QUOTED = re.compile(r"""["'](pypdf|app\.services\.pdf)(\.[\w.]*)?["']""")


def _offences(path: Path, root: Path = BACKEND) -> list[str]:
    source = path.read_text()
    found = []
    tree = ast.parse(source, filename=str(path))
    package = ".".join(path.relative_to(root).with_suffix("").parts[:-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _LIBRARY.match(alias.name) or _PDF_MODULE.match(alias.name):
                    found.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                # `from . import pdf` or `from .pdf import x`, resolved.
                base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                module = ".".join([*base, module] if module else base)
            if _LIBRARY.match(module) or _PDF_MODULE.match(module):
                found.append(f"line {node.lineno}: from {module} import ...")
            elif module == "app.services" and any(a.name == "pdf" for a in node.names):
                found.append(f"line {node.lineno}: from app.services import pdf")
    for match in _QUOTED.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        found.append(f"line {line}: the string {match.group(0)}")
    return found


def test_nothing_outside_the_sandbox_imports_the_pdf_library():
    offences = {}
    for root in SCANNED:
        for path in sorted((BACKEND / root).rglob("*.py")):
            if path in ALLOWED:
                continue
            if problems := _offences(path):
                offences[str(path.relative_to(BACKEND))] = problems
    assert not offences, (
        "Read PDFs through app.services.pdf_sandbox, never in the API process: "
        f"{json.dumps(offences, indent=2)}"
    )


def test_the_scan_catches_every_spelling(tmp_path):
    """The guard proves nothing if it misses the ways round it."""
    spellings = [
        "import pypdf",
        "import pypdf.generic as g",
        "from pypdf import PdfReader",
        "from app.services import pdf",
        "from app.services import storage, pdf as p",
        "from app.services.pdf import page_count",
        "import app.services.pdf",
        "import importlib\nimportlib.import_module('pypdf')",
        '__import__("app.services.pdf")',
    ]
    services = tmp_path / "app" / "services"
    services.mkdir(parents=True)
    for n, spelling in enumerate(spellings):
        module = services / f"m{n}.py"
        module.write_text(spelling + "\n")
        assert _offences(module, tmp_path), spelling
    relative = services / "rel.py"
    relative.write_text("from . import pdf\n")
    assert _offences(relative, tmp_path)
    # And not the sandbox, which is the sanctioned way in.
    fine = services / "fine.py"
    fine.write_text("from app.services import pdf_sandbox\nfrom app.services.pdf_child import Op\n")
    assert not _offences(fine, tmp_path)


_RUNTIME_PROBE = r"""
import asyncio, json, sys
sys.path.insert(0, sys.argv[1])
import app.main  # noqa: F401  the whole app, every router and service
import app.workers.handlers  # noqa: F401  and every job handler
from sqlalchemy import select

from app.db import async_session, engine
from app.models import Base, Booklet, BookletStatus, PastPaper
from app.services import booklets, extraction, storage
from app.services.ai import AiProvider, AiResponse
from app.services.extraction import BookletExtractionResult, ExtractedPaper
from tests.factories import make_subject, org_id

data = open(sys.argv[2], "rb").read()


async def _fake_ai(**kwargs):
    papers = [
        ExtractedPaper(title=f"Paper {n}", session_label="November 2026",
                       paper_number=f"Paper {n}", first_page=2 * n - 1, last_page=2 * n)
        for n in (1, 2)
    ]
    return AiResponse(provider=AiProvider.anthropic, model="probe", prompt_version="probe",
                      input_tokens=1, output_tokens=1,
                      parsed=BookletExtractionResult(papers=papers))


# The calling module's name, as the suite patches it (`QA-7`); no provider is
# ever called (`QA-8`).
extraction.structured_complete = _fake_ai


async def go():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        oid = await org_id(session)
        subject = await make_subject(session, organization_id=oid)
        path, name, mime = await storage.save_bytes(
            data, "application/pdf", "booklet.pdf", organization_id=oid
        )
        booklet = Booklet(organization_id=oid, subject_id=subject.id, file_path=path,
                          file_name=name, file_mime=mime, status=BookletStatus.extracting)
        session.add(booklet)
        await session.commit()
        booklet_id = booklet.id

    # The real booklet read, as its job runs it: the page count goes through
    # the sandbox.
    async with async_session() as session:
        await extraction.extract_booklet(session, {"booklet_id": booklet_id})
        await session.commit()
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        assert booklet.status is BookletStatus.review, booklet.error
        count = booklet.page_count
        booklet.status = BookletStatus.applying
        await session.commit()

    # And the real cut, as its job runs it.
    async with async_session() as session:
        await booklets.split_booklet(session, {"booklet_id": booklet_id})
    async with async_session() as session:
        papers = (await session.scalars(
            select(PastPaper).where(PastPaper.booklet_id == booklet_id))).all()
    return count, len(papers)


count, papers = asyncio.run(go())
print(json.dumps({
    "count": count,
    "papers": papers,
    "loaded": sorted(m for m in sys.modules if m == "pypdf" or m.startswith("pypdf.")
                     or m == "app.services.pdf"),
}))
"""


def test_the_api_process_never_loads_the_pdf_library(tmp_path):
    booklet = tmp_path / "booklet.pdf"
    booklet.write_bytes(_pdf(4))
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "JWT_SECRET": "test-secret-key-0123456789-abcdefghijklmnop",
        "UPLOAD_DIR": str(tmp_path / "uploads"),
    }
    done = subprocess.run(
        [sys.executable, "-I", "-c", _RUNTIME_PROBE, str(BACKEND), str(booklet)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr.decode()[-2000:]
    report = json.loads(done.stdout.decode().strip().splitlines()[-1])
    assert report["count"] == 4
    assert report["papers"] == 2
    assert report["loaded"] == []
