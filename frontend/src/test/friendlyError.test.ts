import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { friendlyError } from "../lib/errors";

describe("friendlyError", () => {
  it("says busy when the server turned the request away under load", () => {
    expect(friendlyError(new ApiError(503, "anything"))).toBe(
      "Avora is busy right now. Please try again in a moment.",
    );
  });

  it("keeps the generic sentence for other server errors", () => {
    expect(friendlyError(new ApiError(500, "Internal Server Error"))).toBe(
      "Something went wrong on our side. Try again in a minute.",
    );
  });
});
