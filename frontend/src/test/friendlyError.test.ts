import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { friendlyError } from "../lib/errors";

describe("friendlyError", () => {
  it("says busy when the server turned the request away under load", () => {
    const busy = "Avora is busy right now. Please try again in a moment.";
    expect(friendlyError(new ApiError(503, busy))).toBe(busy);
  });

  it("does not call another 503, such as an unconfigured integration, busy", () => {
    expect(friendlyError(new ApiError(503, "Google Classroom is not configured"))).toBe(
      "Something went wrong on our side. Try again in a minute.",
    );
  });

  it("keeps the generic sentence for other server errors", () => {
    expect(friendlyError(new ApiError(500, "Internal Server Error"))).toBe(
      "Something went wrong on our side. Try again in a minute.",
    );
  });
});
