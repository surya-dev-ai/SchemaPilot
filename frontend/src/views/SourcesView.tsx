import { useEffect, useMemo, useState } from "react";
import { formatApiError, getSchema, listSources } from "../api/client";
import type { SchemaSnapshot, SourceSummary, TableSnapshot } from "../api/types";
import { ApiError } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; sources: SourceSummary[] }
  | { kind: "error"; message: string };
type SchemaState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; value: SchemaSnapshot }
  | { kind: "unavailable"; message: string }
  | { kind: "error"; message: string };

export function SourcesView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [schemaState, setSchemaState] = useState<SchemaState>({ kind: "idle" });
  const [query, setQuery] = useState("");
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());

  async function refreshSources(signal?: AbortSignal) {
    setState({ kind: "loading" });
    try {
      const body = await listSources(signal);
      if (!signal?.aborted) setState({ kind: "ready", sources: body.sources });
    } catch (error) {
      if (!signal?.aborted) setState({ kind: "error", message: formatApiError(error) });
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void refreshSources(controller.signal);
    return () => controller.abort();
  }, []);

  async function inspect(sourceId: string) {
    setSelectedId(sourceId);
    setSchemaState({ kind: "loading" });
    setQuery("");
    setExpandedTables(new Set());
    try {
      const schema = await getSchema();
      setSchemaState({ kind: "ready", value: schema });
    } catch (error) {
      if (error instanceof ApiError && (error.code === "source_unavailable" || error.code === "source_not_configured")) {
        setSchemaState({ kind: "unavailable", message: "This source is listed, but schema inspection is currently unavailable." });
      } else {
        setSchemaState({ kind: "error", message: formatApiError(error) });
      }
    }
  }

  const schema = schemaState.kind === "ready" ? schemaState.value : null;
  const filteredTables = useMemo(() => {
    if (!schema) return [];
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return schema.tables;
    return schema.tables.filter((table) =>
      [table.name, ...table.columns.map((column) => column.name)].some((item) => item.toLocaleLowerCase().includes(needle)),
    );
  }, [schema, query]);

  function toggleTable(id: string) {
    setExpandedTables((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (state.kind === "loading") return <div className="loading-card" role="status">Loading available sources…</div>;
  if (state.kind === "error") return <div className="stack"><ErrorBanner title="Sources unavailable" message={state.message} /><button type="button" onClick={() => void refreshSources()}>Try again</button></div>;

  const selected = state.sources.find((source) => source.id === selectedId);
  return (
    <div className="page-stack">
      <div className="page-heading">
        <div><p className="eyebrow">Workspace</p><h2>Data sources</h2><p className="page-description">Choose a source to inspect its schema. Schema details load only when you ask to view them.</p></div>
        <span className="status-pill status-safe"><span className="status-dot" /> Read-only inspection</span>
      </div>
      <section className="source-grid" aria-label="Available data sources">
        {state.sources.length === 0 ? <div className="empty-state"><h3>No sources available</h3><p>Configured sources will appear here when they are available.</p></div> : null}
        {state.sources.map((source) => (
          <article className={`source-card${selectedId === source.id ? " source-card-selected" : ""}`} key={source.id}>
            <div className="source-card-top"><span className="source-icon" aria-hidden="true">DB</span><span className={`status-pill ${source.configured ? "status-ready" : "status-muted"}`}><span className="status-dot" /> {source.configured ? "Available" : "Not configured"}</span></div>
            <h3>{source.display_name}</h3><p className="muted">Read-only source · Schema inspection</p>
            <button type="button" className="button-primary" disabled={!source.configured} onClick={() => void inspect(source.id)}>{selectedId === source.id ? "Refresh schema" : "Inspect schema"}</button>
          </article>
        ))}
      </section>
      {selected ? (
        <section className="schema-section" aria-live="polite">
          <div className="section-heading"><div><p className="eyebrow">Selected source</p><h3>{selected.display_name}</h3></div>{schema ? <span className="schema-count">{schema.tables.length} {schema.tables.length === 1 ? "table" : "tables"}</span> : null}</div>
          {schemaState.kind === "loading" ? <div className="loading-card" role="status">Inspecting schema…</div> : null}
          {schemaState.kind === "unavailable" ? <p className="banner banner-warn">{schemaState.message}</p> : null}
          {schemaState.kind === "error" ? <div className="stack"><ErrorBanner title="Schema inspection failed" message={schemaState.message} /><button type="button" onClick={() => void inspect(selected.id)}>Try again</button></div> : null}
          {schema ? (
            <>
              <div className="schema-toolbar"><label className="search-field"><span className="sr-only">Search tables and columns</span><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search tables or columns" /></label><span className="muted">{filteredTables.length} of {schema.tables.length} tables</span></div>
              {schema.tables.length === 0 ? <p className="empty-state">No tables were found in this source.</p> : null}
              {schema.tables.length > 0 && filteredTables.length === 0 ? <p className="empty-state">No tables or columns match “{query}”.</p> : null}
              <div className="table-list">{filteredTables.map((table) => <TableCard key={table.id} table={table} expanded={expandedTables.has(table.id)} onToggle={() => toggleTable(table.id)} />)}</div>
              {schema.dependencies.length > 0 ? <details className="technical-details"><summary>Relationships <span className="muted">{schema.dependencies.length}</span></summary><ul className="relationship-list">{schema.dependencies.map((item) => <li key={item.id}><span>{item.from_table}.{item.from_columns.join(", ")}</span><span className="relationship-arrow" aria-label="references">→</span><span>{item.to_table}.{item.to_columns.join(", ")}</span></li>)}</ul></details> : null}
              <details className="technical-details fingerprint-details"><summary>Technical details</summary><dl className="inline-facts"><div><dt>Schema</dt><dd>{schema.schema_name}</dd></div><div><dt>Schema fingerprint</dt><dd className="mono">{schema.fingerprint}</dd></div></dl></details>
            </>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function TableCard({ table, expanded, onToggle }: { table: TableSnapshot; expanded: boolean; onToggle: () => void }) {
  return (
    <article className="table-card">
      <button type="button" className="table-toggle" aria-expanded={expanded} onClick={onToggle}><span className={`chevron${expanded ? " chevron-open" : ""}`} aria-hidden="true">›</span><span className="table-title">{table.name}</span><span className="table-meta">{table.columns.length} columns</span><span className="table-meta">{table.indexes.length} indexes</span></button>
      {expanded ? (
        <div className="table-content"><div className="column-list">{table.columns.map((column) => <div className="column-row" key={column.id}><span className="column-name">{column.name}</span><span className="column-type">{column.data_type}</span><span className="column-nullability">{column.nullable ? "Nullable" : "Required"}</span></div>)}</div>
          {(table.constraints.length > 0 || table.indexes.length > 0) ? <details className="table-extra-details"><summary>Constraints and indexes</summary><div className="extra-lists">
            {table.constraints.length ? <div><h4>Constraints</h4><ul>{table.constraints.map((constraint) => <li key={constraint.id}><strong>{constraint.name}</strong> · {constraint.kind}{constraint.columns.length ? ` on ${constraint.columns.join(", ")}` : ""}{constraint.referenced_table ? ` → ${constraint.referenced_table}(${constraint.referenced_columns.join(", ")})` : ""}{constraint.check_expression ? <pre className="code-block">{constraint.check_expression}</pre> : null}</li>)}</ul></div> : null}
            {table.indexes.length ? <div><h4>Indexes</h4><ul>{table.indexes.map((index) => <li key={index.id}><strong>{index.name}</strong> · {index.unique ? "Unique" : "Index"} on {index.columns.join(", ")}</li>)}</ul></div> : null}
          </div></details> : null}
        </div>
      ) : null}
    </article>
  );
}
