import AddItemForm from "./components/AddItemForm";
import AskPanel from "./components/AskPanel";
import ItemList from "./components/ItemList";
import { useItems } from "./hooks/useItems";

export default function App() {
  const { items, loading, error, refresh } = useItems();

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-4 py-4">
          <h1 className="text-lg font-semibold">Knowledge Inbox</h1>
          <p className="text-sm text-slate-500">
            Save notes and links, then ask questions over them.
          </p>
        </div>
      </header>

      <main className="mx-auto grid max-w-5xl gap-6 px-4 py-6 md:grid-cols-2">
        <div className="space-y-4">
          <AddItemForm onAdded={refresh} />
          <ItemList items={items} loading={loading} error={error} />
        </div>
        <AskPanel />
      </main>
    </div>
  );
}
