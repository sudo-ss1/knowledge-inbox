import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ItemSummary } from "../types";
import ItemList from "./ItemList";

function item(overrides: Partial<ItemSummary> = {}): ItemSummary {
  return {
    id: "itm_1",
    type: "note",
    title: "Kafka notes",
    source: null,
    status: "ready",
    error: null,
    chunk_count: 3,
    preview: "A rebalance is triggered when membership changes.",
    created_at: "2026-09-10T00:00:00Z",
    ...overrides,
  };
}

describe("ItemList", () => {
  it("renders a saved item with its title and preview", () => {
    render(<ItemList items={[item()]} loading={false} error={null} />);

    expect(screen.getByText("Kafka notes")).toBeInTheDocument();
    expect(screen.getByText(/membership changes/)).toBeInTheDocument();
    expect(screen.getByText(/3 chunks/)).toBeInTheDocument();
  });

  it("shows the failure reason inline on a failed item", () => {
    render(
      <ItemList
        items={[item({ status: "failed", error: "Upstream returned HTTP 404." })]}
        loading={false}
        error={null}
      />,
    );

    expect(screen.getByText("Upstream returned HTTP 404.")).toBeInTheDocument();
  });

  it("marks a pending item as indexing", () => {
    render(<ItemList items={[item({ status: "pending" })]} loading={false} error={null} />);

    expect(screen.getByText(/indexing/i)).toBeInTheDocument();
  });

  it("links a url item to its source", () => {
    render(
      <ItemList
        items={[item({ type: "url", source: "https://example.com/post" })]}
        loading={false}
        error={null}
      />,
    );

    expect(screen.getByRole("link")).toHaveAttribute("href", "https://example.com/post");
  });

  it("explains an empty inbox", () => {
    render(<ItemList items={[]} loading={false} error={null} />);

    expect(screen.getByText(/nothing saved yet/i)).toBeInTheDocument();
  });

  it("shows a load error", () => {
    render(<ItemList items={[]} loading={false} error="network down" />);

    expect(screen.getByRole("alert")).toHaveTextContent("network down");
  });
});
