import { useCatalogState } from "./catalog-state";
import { CatalogVisibility } from "./features/catalog-visibility/CatalogVisibility";

export function App() {
  const catalog = useCatalogState();

  return <CatalogVisibility state={catalog.state} onRetry={catalog.retry} />;
}
