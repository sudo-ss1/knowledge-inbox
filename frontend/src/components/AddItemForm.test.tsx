import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import AddItemForm from "./AddItemForm";

vi.mock("../api/client", () => ({
  api: { ingestNote: vi.fn(), ingestUrl: vi.fn() },
  ApiError: class extends Error {},
}));

afterEach(() => vi.clearAllMocks());

describe("AddItemForm", () => {
  it("submits a note and notifies the parent", async () => {
    vi.mocked(api.ingestNote).mockResolvedValue({
      id: "itm_1",
      type: "note",
      status: "pending",
      created_at: "now",
    });
    const onAdded = vi.fn();
    render(<AddItemForm onAdded={onAdded} />);

    await userEvent.type(screen.getByLabelText(/note/i), "Kafka rebalances on rejoin.");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(api.ingestNote).toHaveBeenCalledWith("Kafka rebalances on rejoin."));
    expect(onAdded).toHaveBeenCalled();
  });

  it("submits a url after switching mode", async () => {
    vi.mocked(api.ingestUrl).mockResolvedValue({
      id: "itm_2",
      type: "url",
      status: "pending",
      created_at: "now",
    });
    render(<AddItemForm onAdded={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /^url$/i }));
    await userEvent.type(screen.getByLabelText(/url/i), "https://example.com/post");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(api.ingestUrl).toHaveBeenCalledWith("https://example.com/post"),
    );
  });

  it("clears the input after a successful save", async () => {
    vi.mocked(api.ingestNote).mockResolvedValue({
      id: "itm_1",
      type: "note",
      status: "pending",
      created_at: "now",
    });
    render(<AddItemForm onAdded={vi.fn()} />);
    const field = screen.getByLabelText(/note/i);

    await userEvent.type(field, "something worth keeping");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(field).toHaveValue(""));
  });

  it("clears the field's value when switching modes", async () => {
    render(<AddItemForm onAdded={vi.fn()} />);

    await userEvent.type(screen.getByLabelText(/note/i), "leftover note text");
    await userEvent.click(screen.getByRole("button", { name: /^url$/i }));

    expect(screen.getByLabelText(/url/i)).toHaveValue("");
  });

  it("refuses to submit an empty note", async () => {
    render(<AddItemForm onAdded={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(api.ingestNote).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/cannot be empty/i);
  });

  it("refuses a url that is not http", async () => {
    render(<AddItemForm onAdded={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /^url$/i }));
    await userEvent.type(screen.getByLabelText(/url/i), "ftp://example.com");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(api.ingestUrl).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/http/i);
  });

  it("shows the server message when the save fails", async () => {
    vi.mocked(api.ingestNote).mockRejectedValue(new Error("Set OPENAI_API_KEY and restart."));
    render(<AddItemForm onAdded={vi.fn()} />);

    await userEvent.type(screen.getByLabelText(/note/i), "a note");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/OPENAI_API_KEY/),
    );
  });
});
