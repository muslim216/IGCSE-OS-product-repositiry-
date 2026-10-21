import { afterEach, describe, expect, test, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { UploadRefused } from "../lib/uploadRefused";
import {
  MAX_FILE_BYTES,
  MAX_FILES_PER_UPLOAD,
  checkFiles,
  prepareFiles,
  useUpload,
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
    seen: [0, 0] as number[],
    toBlob(cb: (b: Blob | null) => void) {
      canvas.seen = [canvas.width, canvas.height];
      cb(new Blob([new Uint8Array(outBytes)], { type: "image/jpeg" }));
    },
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
    expect(canvas.seen).toEqual([2000, 1500]);
    // and handed back once the blob exists
    expect([canvas.width, canvas.height]).toEqual([0, 0]);
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

describe("edge cases", () => {
  test("an empty file is refused by name", () => {
    expect(() => checkFiles([fakeFile("blank.jpg", "image/jpeg", 0)])).toThrow(
      "blank.jpg is empty",
    );
  });

  test("a file with no MIME type but a .jpg name is still shrunk", async () => {
    mockImaging(4000, 3000, 300_000);
    const out = await shrinkImage(fakeFile("IMG_9.JPG", "", 5 * MB));
    expect(out.type).toBe("image/jpeg");
    expect(out.size).toBe(300_000);
  });

  test("the bitmap is closed even when drawing throws", async () => {
    const { bitmap, ctx } = mockImaging(4000, 3000, 1000);
    ctx.drawImage.mockImplementation(() => {
      throw new Error("out of memory");
    });
    const f = fakeFile("a.jpg", "image/jpeg", 5 * MB);
    expect(await shrinkImage(f)).toBe(f);
    expect(bitmap.close).toHaveBeenCalledTimes(1);
  });

  test("cancelling while preparing stops before the next photo", async () => {
    const decode = vi.fn(async () => ({ width: 100, height: 100, close: vi.fn() }));
    vi.stubGlobal("createImageBitmap", decode);
    const ac = new AbortController();
    decode.mockImplementationOnce(async () => {
      ac.abort();
      return { width: 100, height: 100, close: vi.fn() };
    });
    const files = [1, 2, 3].map((i) => fakeFile(`p${i}.jpg`, "image/jpeg", MB));
    await expect(prepareFiles(files, ac.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(decode).toHaveBeenCalledTimes(1);
  });
});

describe("useUpload", () => {
  const pdf = () => fakeFile("a.pdf", "application/pdf", 1000);

  test("leaving the page aborts the request in flight", async () => {
    let signal!: AbortSignal;
    const { result, unmount } = renderHook(() => useUpload());
    let p!: Promise<unknown>;
    act(() => {
      p = result.current.run([pdf()], (_f, o) => {
        signal = o.signal;
        return new Promise(() => {});
      });
      p.catch(() => {});
    });
    await vi.waitFor(() => expect(signal).toBeDefined());
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });

  test("leaving during processing lets the request finish", async () => {
    let signal!: AbortSignal;
    let finish!: (v: string) => void;
    const { result, unmount } = renderHook(() => useUpload());
    let p!: Promise<string>;
    act(() => {
      p = result.current.run([pdf()], (_f, o) => {
        signal = o.signal;
        o.onSent();
        return new Promise<string>((res) => {
          finish = res;
        });
      });
    });
    await vi.waitFor(() => expect(result.current.phase).toBe("processing"));
    unmount();
    expect(signal.aborted).toBe(false);
    finish("saved");
    await expect(p).resolves.toBe("saved");
  });

  test("a new run aborts the old one, and the old one's end leaves the new state alone", async () => {
    const signals: AbortSignal[] = [];
    let release1!: () => void;
    const { result } = renderHook(() => useUpload());
    let first!: Promise<unknown>;
    act(() => {
      first = result.current.run([pdf()], (_f, o) => {
        signals.push(o.signal);
        return new Promise((_res, rej) => {
          release1 = () => rej(new DOMException("x", "AbortError"));
        });
      });
      first.catch(() => {});
    });
    await vi.waitFor(() => expect(signals).toHaveLength(1));
    act(() => {
      result.current.run([pdf()], (_f, o) => {
        signals.push(o.signal);
        o.onProgress(40);
        return new Promise(() => {});
      });
    });
    await vi.waitFor(() => expect(result.current.percent).toBe(40));
    expect(signals[0].aborted).toBe(true);
    await act(async () => {
      release1();
      await first.catch(() => {});
    });
    // the first run finishing must not reset the second's bar or mark a cancel
    expect(result.current.percent).toBe(40);
    expect(result.current.phase).toBe("sending");
    expect(result.current.cancelled).toBe(false);
  });

  test("no percent is shown until the browser reports one, and 100 means processing", async () => {
    const { result } = renderHook(() => useUpload());
    let emit!: (p: number) => void;
    act(() => {
      result.current
        .run([pdf()], (_f, o) => {
          emit = o.onProgress;
          return new Promise(() => {});
        })
        .catch(() => {});
    });
    await vi.waitFor(() => expect(result.current.phase).toBe("sending"));
    expect(result.current.percent).toBeNull();
    act(() => emit(50));
    expect(result.current.announcement).toBe("Sending, 50 percent");
    act(() => emit(100));
    expect(result.current.phase).toBe("processing");
  });
});
