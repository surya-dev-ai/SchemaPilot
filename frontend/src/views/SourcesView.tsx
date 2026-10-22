import { useEffect, useState } from "react";
import { formatApiError, getSchema, listSources } from "../api/client";
import type { SchemaSnapshot, SourceSummary } from "../api/types";
import { ApiError } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; sources: SourceSummary[]; schema: SchemaSnapshot | null; note: string | null }
  | { kind: "error"; message: string };

export function SourcesView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const listed = await listSources(controller.signal);
        let schema: SchemaSnapshot | null = null;
        let note: string | null = null;
        try {
          schema = await getSchema(controller.signal);
          if (schema.tables.length === 0) {
            note =
              "Inspection succeeded, but the snapshot contains no tables. " +
              "That is different from an unavailable database.";
          }
        } catch (error) {
          if (error instanceof ApiError && error.code === "source_unavailable") {
            note =
              "The source database is unavailable. Listing still succeeded; " +
              "schema inspection did not.";
          } else if (error instanceof ApiError && error.code === "source_not_configured") {
            note = "The bookstore source is listed but not configured.";
          } else {
            throw error;
          }
        }
        if (!controller.signal.aborted) {
          setState({ kind: "ready", sources: listed.sources, schema, note });
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setState({ kind: "error", message: formatApiError(error) });
        }
      }
    }
    void load();
    return () => controller.abort();
  }, []);

  if (state.kind === "loading") {
    return <p>Loading sources.</p>;
  }
  if (state.kind === "error") {
    return <ErrorBanner message={state.message} />;
  }

  return (
    <div className="stack">
      <p className="lead">
        Sources come from <code>GET /api/v1/sources</code>. Schema details come from{" "}
        <code>GET /api/v1/sources/bookstore-demo/schema</code>.
      </p>
      {state.note ? <p className="banner banner-warn">{state.note}</p> : null}
      <ul className="plain-list">
        {state.sources.map((source) => (
          <li key={source.id}>
            <strong>{source.display_name}</strong> ({source.id}) — database{" "}
            {source.database_name}, schema {source.schema_name}, access {source.access},{" "}
            {source.configured ? "configured" : "not configured"}
          </li>
        ))}
      </ul>
      {state.schema ? (
        <>
          <h3>Fingerprint</h3>
          <p className="mono">{state.schema.fingerprint}</p>
          <h3>Tables</h3>
          {state.schema.tables.map((table) => (
            <article key={table.id} className="panel">
              <h4>{table.name}</h4>
              {table.comment ? (
                <p className="muted">
                  Table comment (untrusted metadata): <code>{table.comment}</code>
                </p>
              ) : null}
              <h5>Columns</h5>
              <ul>
                {table.columns.map((column) => (
                  <li key={column.id}>
                    {column.name} — {column.data_type}
                    {column.nullable ? ", nullable" : ", not null"}
                    {column.comment ? (
                      <>
                        {" "}
                        · comment (untrusted): <code>{column.comment}</code>
                      </>
                    ) : null}
                  </li>
                ))}
              </ul>
              <h5>Constraints</h5>
              <ul>
                {table.constraints.map((constraint) => (
                  <li key={constraint.id}>
                    {constraint.name} ({constraint.kind}) on {constraint.columns.join(", ")}
                    {constraint.check_expression ? (
                      <>
                        {" "}
                        · expression (untrusted): <code>{constraint.check_expression}</code>
                      </>
                    ) : null}
                  </li>
                ))}
              </ul>
              <h5>Indexes</h5>
              <ul>
                {table.indexes.map((index) => (
                  <li key={index.id}>
                    {index.name} on {index.columns.join(", ")}
                    {index.unique ? " (unique)" : ""}
                  </li>
                ))}
              </ul>
            </article>
          ))}
          <h3>Dependencies</h3>
          <ul>
            {state.schema.dependencies.map((dependency) => (
              <li key={dependency.id}>
                {dependency.from_table}.{dependency.from_columns.join(",")} →{" "}
                {dependency.to_table}.{dependency.to_columns.join(",")} (
                {dependency.constraint_name})
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}
