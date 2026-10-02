import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { GroupResourcesPanel } from "../tutor/GroupResourcesPanel";

/* A class's files and recordings. What has to hold: nothing the tutor can no
   longer see is acted on — not a file from a picker that has gone away, and
   not a removal confirmed for a class they have since left. */

const WORKSHEET = {
  id: 10,
  group_id: 1,
  kind: "file" as const,
  title: "Moles worksheet",
  url: null,
  file_name: "moles.pdf",
  created_at: "2026-09-20T10:00:00Z",
};

function stub() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (path === "/api/v1/groups/1/resources") return json([WORKSHEET]);
      return json([]);
    }),
  );
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

afterEach(() => vi.unstubAllGlobals());

test("a file chosen before switching type away and back is not uploaded unseen", async () => {
  stub();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<GroupResourcesPanel groupId={1} />, { wrapper: wrapper(client) });
  await screen.findByRole("button", { name: "Remove Moles worksheet" });

  fireEvent.change(screen.getByLabelText("Type"), { target: { value: "file" } });
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Lesson 4" } });
  fireEvent.change(screen.getByLabelText("File"), {
    target: { files: [new File(["%PDF-1.4"], "lesson4.pdf", { type: "application/pdf" })] },
  });
  const add = screen.getByRole("button", { name: "Add" });
  expect(add).toBeEnabled();

  // The picker unmounts with the type and comes back empty — so must the file.
  fireEvent.change(screen.getByLabelText("Type"), { target: { value: "recording" } });
  fireEvent.change(screen.getByLabelText("Type"), { target: { value: "file" } });
  expect(screen.getByText("Choose a file")).toBeInTheDocument();
  expect(add).toBeDisabled();
});

test("an open removal does not follow the tutor to another class", async () => {
  stub();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { rerender } = render(<GroupResourcesPanel groupId={1} />, { wrapper: wrapper(client) });

  fireEvent.click(await screen.findByRole("button", { name: "Remove Moles worksheet" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();

  // The same mounted panel, now for class 2 — what a cached class's route does.
  rerender(<GroupResourcesPanel groupId={2} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
