/**
 * API-11: a validation failure has to name the field and the problem.
 *
 * FastAPI answers schema validation with `{"detail": [{loc, msg, type}, …]}`.
 * `client.ts` used to read `detail` only when it was a string, so every one of
 * those fell through to `resp.statusText` and the user was told
 * "Unprocessable Entity" — a phrase that names neither the field they got
 * wrong nor what was wrong with it.
 *
 * The negative cases matter more than the positive ones here: the bug was not
 * that the good path was missing, it was that the bad path silently discarded
 * everything it did not recognise.
 */
import { afterEach, describe, expect, test, vi } from "vitest";
import { ApiError, api, parseErrorBody } from "../api/client";

describe("string detail — the shape that already worked", () => {
  test("a handler-raised HTTPException is passed through unchanged", () => {
    expect(parseErrorBody({ detail: "Tutor account required" })).toEqual({
      detail: "Tutor account required",
      fields: [],
    });
  });
});

describe("list detail — FastAPI's 422, the shape that was discarded", () => {
  test("a missing field names itself and the problem", () => {
    const { detail, fields } = parseErrorBody({
      detail: [{ loc: ["body", "email"], msg: "Field required", type: "missing" }],
    });
    expect(detail).toBe("Email: Field required");
    expect(fields).toEqual([
      { path: "email", label: "Email", message: "Field required" },
    ]);
  });

  test("the loc source prefix is dropped — the user did not choose it", () => {
    const { fields } = parseErrorBody({
      detail: [{ loc: ["query", "student_id"], msg: "Input should be a valid integer" }],
    });
    expect(fields[0].path).toBe("student_id");
    expect(fields[0].label).toBe("Student id");
  });

  test("a nested index is reported 1-based, the way the user counts it", () => {
    const { detail, fields } = parseErrorBody({
      detail: [{ loc: ["body", "questions", 0, "max_marks"], msg: "Field required" }],
    });
    expect(fields[0].path).toBe("questions.0.max_marks");
    expect(detail).toBe("Questions → #1 → Max marks: Field required");
  });

  test("several failures are all reported, not just the first", () => {
    const { detail, fields } = parseErrorBody({
      detail: [
        { loc: ["body", "email"], msg: "Field required" },
        { loc: ["body", "password"], msg: "String should have at least 8 characters" },
      ],
    });
    expect(fields).toHaveLength(2);
    expect(detail).toBe(
      "Email: Field required; Password: String should have at least 8 characters",
    );
  });

  test("a whole-body error keeps its message even with no field to name", () => {
    const { detail, fields } = parseErrorBody({
      detail: [{ loc: ["body"], msg: "Input should be a valid dictionary" }],
    });
    expect(fields[0].label).toBe("");
    expect(detail).toBe("Input should be a valid dictionary");
  });
});

describe("bodies that tell us nothing", () => {
  // Each of these must yield an empty detail so the caller falls back to
  // resp.statusText. Returning "" as though it were a message would leave the
  // user with a blank error box, which is worse than "Unprocessable Entity".
  test.each([
    ["null body", null],
    ["no detail key", { message: "nope" }],
    ["detail is a number", { detail: 500 }],
    ["empty list", { detail: [] }],
    ["list of non-objects", { detail: ["boom", 3] }],
    ["list entries with no msg", { detail: [{ loc: ["body", "x"] }] }],
  ])("%s yields no detail so statusText is used", (_name, body) => {
    expect(parseErrorBody(body).detail).toBe("");
  });

  test("a malformed entry is skipped without losing its well-formed siblings", () => {
    const { fields } = parseErrorBody({
      detail: [{ loc: ["body", "a"] }, { loc: ["body", "b"], msg: "Field required" }],
    });
    expect(fields).toHaveLength(1);
    expect(fields[0].path).toBe("b");
  });

  test("a missing loc still reports the message rather than dropping it", () => {
    const { detail } = parseErrorBody({ detail: [{ msg: "Field required" }] });
    expect(detail).toBe("Field required");
  });
});

describe("through api() — the path the user actually hits", () => {
  // parseErrorBody being right is not the fix; the fix is that a real 422
  // reaches a real form as readable text. These stub fetch to prove the wiring
  // rather than the parser.
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  /** Await a call that must reject, and hand back the ApiError it rejected with. */
  async function rejection(call: Promise<unknown>): Promise<ApiError> {
    const err = await call.then(
      () => null,
      (e: unknown) => e,
    );
    expect(err, "the call resolved when it should have thrown").toBeInstanceOf(ApiError);
    return err as ApiError;
  }

  function respondWith(status: number, body: unknown) {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status,
        statusText: "Unprocessable Entity",
        json: async () => body,
      }),
    );
  }

  test("a 422 surfaces the field and the problem, not 'Unprocessable Entity'", async () => {
    respondWith(422, {
      detail: [{ loc: ["body", "target_grade"], msg: "Input should be a valid integer" }],
    });

    const err = await rejection(api("/api/v1/students/1"));

    expect(err.status).toBe(422);
    expect(err.message).toBe("Target grade: Input should be a valid integer");
    expect(err.fields).toEqual([
      {
        path: "target_grade",
        label: "Target grade",
        message: "Input should be a valid integer",
      },
    ]);
  });

  test("a 403 with a string detail is unchanged — no regression on what worked", async () => {
    respondWith(403, { detail: "Tutor account required" });

    const err = await rejection(api("/api/v1/groups"));

    expect(err.message).toBe("Tutor account required");
    expect(err.fields).toEqual([]);
  });

  test("an unreadable body still falls back to statusText, never to blank", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        statusText: "Bad Gateway",
        json: async () => {
          throw new SyntaxError("not JSON");
        },
      }),
    );

    const err = await rejection(api("/api/v1/groups"));

    expect(err.message).toBe("Bad Gateway");
  });
});
