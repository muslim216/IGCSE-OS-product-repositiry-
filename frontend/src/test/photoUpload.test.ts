import { afterEach, describe, expect, test, vi } from "vitest";
import {
  MAX_FILE_BYTES,
  MAX_FILES_PER_UPLOAD,
  UploadRefused,
  checkFiles,
  prepareFiles,
  shrinkImage,
  shrunkSize,
} from "../lib/photoUpload";

const MB = 1024 * 1024;

function fakeFile(name: string, type: string, size: number): File {
  const f = new File(["x"], name, { type });
  Object.defineProperty(f, "size", { value: size });
  return f;
}

function mockImaging(width: number, height: number, outBytes: number) {
  const bitmap = { width, height, close: vi.fn() };
  vi.stubGlobal(
    "createImageBitmap",
    vi.fn(async () => bitmap),
  );
  const ctx = { fillRect: vi.fn(), drawImage: vi.fn(), fillStyle: "" };
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ctx,
    toBlob: (cb: (b: Blob | null) => void) =>
      cb(new Blob([new Uint8Array(outBytes)], { type: "image/jpeg" })),
  };
  vi.spyOn(document, "createElement").mockReturnValue(canvas as unknown as HTMLElement);
  return { bitmap, canvas, ctx };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("shrunkSize", () => {
  test("scales the longest side to 2000, keeping the ratio", () => {
    expect(shrunkSize(4000, 3000)).toEqual({ w: 2000, h: 1500 });
    expect(shrunkSize(3000, 4000)).toEqual({ w: 1500, h: 2000 });
  });
  test("leaves anything at or under 2000 alone", () => {
    expect(shrunkSize(2000, 1000)).toBeNull();
    expect(shrunkSize(800, 600)).toBeNull();
  });
});

describe("shrinkImage", () => {
  test("a big photo becomes a 2000 px JPEG at 0.85 with a .jpg name", async () => {
    const { canvas, bitmap } = mockImaging(4000, 3000, 300_000);
    const toBlob = vi.spyOn(canvas, "toBlob");
    const out = await shrinkImage(fakeFile("page-1.png", "image/png", 5 * MB));
    expect(createImageBitmap).toHaveBeenCalledWith(expect.anything(), {
      imageOrientation: "from-image",
    });
    expect([canvas.width, canvas.height]).toEqual([2000, 1500]);
    expect(toBlob).toHaveBeenCalledWith(expect.any(Function), "image/jpeg", 0.85);
    expect(out.name).toBe("page-1.jpg");
    expect(out.type).toBe("image/jpeg");
    expect(bitmap.close).toHaveBeenCalled();
  });

  test("a small photo is returned as it came", async () => {
    mockImaging(1600, 1200, 1000);
    const f = fakeFile("small.jpg", "image/jpeg", 2 * MB);
    expect(await shrinkImage(f)).toBe(f);
  });

  test("PDFs and HEIC are never decoded", async () => {
    mockImaging(4000, 3000, 1000);
    const pdf = fakeFile("a.pdf", "application/pdf", 3 * MB);
    const heic = fakeFile("IMG_1.HEIC", "image/heic", 3 * MB);
    const noType = fakeFile("IMG_2.heic", "", 3 * MB);
    expect(await shrinkImage(pdf)).toBe(pdf);
    expect(await shrinkImage(heic)).toBe(heic);
    expect(await shrinkImage(noType)).toBe(noType);
    expect(createImageBitmap).not.toHaveBeenCalled();
  });

  test("keeps the original when decoding fails", async () => {
    vi.stubGlobal("createImageBitmap", vi.fn().mockRejectedValue(new Error("nope")));
    const f = fakeFile("a.jpg", "image/jpeg", 3 * MB);
    expect(await shrinkImage(f)).toBe(f);
  });

  test("keeps the original when the result is not smaller", async () => {
    mockImaging(4000, 3000, 6 * MB);
    const f = fakeFile("a.jpg", "image/jpeg", 5 * MB);
    expect(await shrinkImage(f)).toBe(f);
  });
});

describe("checkFiles", () => {
  test("names the file that is too big", () => {
    const f = fakeFile("photo-12.jpg", "image/jpeg", 24 * MB);
    expect(() => checkFiles([f])).toThrow(
      "photo-12.jpg is too big (24 MB). The limit is 20 MB per file.",
    );
  });
  test("a file exactly at the limit passes", () => {
    expect(() => checkFiles([fakeFile("a.pdf", "application/pdf", MAX_FILE_BYTES)])).not.toThrow();
  });
  test("too many files", () => {
    const files = Array.from({ length: MAX_FILES_PER_UPLOAD + 1 }, (_, i) =>
      fakeFile(`p${i}.jpg`, "image/jpeg", 1000),
    );
    expect(() => checkFiles(files)).toThrow("You picked 41 files. The limit is 40 per hand-in.");
  });
  test("too big all together", () => {
    const files = Array.from({ length: 9 }, (_, i) =>
      fakeFile(`p${i}.pdf`, "application/pdf", 19 * MB),
    );
    expect(() => checkFiles(files)).toThrow(UploadRefused);
  });
});

describe("prepareFiles", () => {
  test("a 24 MB photo that shrinks small enough is accepted", async () => {
    mockImaging(5000, 4000, 400_000);
    const out = await prepareFiles([fakeFile("big.jpg", "image/jpeg", 24 * MB)]);
    expect(out[0].name).toBe("big.jpg");
    expect(out[0].size).toBe(400_000);
  });
  test("a 24 MB PDF is refused by name", async () => {
    await expect(prepareFiles([fakeFile("scan.pdf", "application/pdf", 24 * MB)])).rejects.toThrow(
      "scan.pdf is too big",
    );
  });
});
