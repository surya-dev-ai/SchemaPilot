# SchemaPilot UI/UX Redesign Draft

**Status:** Implemented and verified in the frontend  
**Scope:** Frontend presentation and interaction design, with safe handling of database metadata.

## Goal

Make SchemaPilot feel like a focused, professional migration workspace. Keep the core journey visible: choose a source, describe a change, inspect the proposal, validate it in the sandbox, and review its recorded outcome.

## Privacy and database visibility

- Do not present connection strings, credentials, hostnames, ports, or internal application database configuration in the normal user interface.
- Keep operational configuration in a restricted/admin surface; show safe status labels rather than raw infrastructure details.
- The schema browser may show metadata for the explicitly selected source because users need it to understand migration impact. It should not dump every source and every object in one unstructured page.
- Present source identity and access level first. Put tables, columns, constraints, indexes, and relationships behind a deliberate selection and progressive disclosure (search, expand/collapse, counts).
- Avoid exposing sensitive-looking comments or arbitrary database metadata by default. Render metadata as text, never as executable markup; make it opt-in where useful.
- Keep target execution disabled and make the sandbox boundary clear in the UI.

## Proposed experience

1. **Workspace shell:** clear product header, compact service/safety indicators, responsive navigation, consistent page titles and descriptions.
2. **Sources:** source cards with a concise summary, configured/available state, and an explicit “Inspect schema” action. Schema detail uses searchable, collapsible table panels with column and relationship summaries.
3. **New migration:** prominent request composer with a few useful example prompts, clear validation/loading/error states, and a visible “sandbox only” explanation.
4. **History and details:** scannable status, timestamps, and request summaries; keep sensitive SQL/details behind intentional expansion where supported by existing contracts.
5. **Settings:** concise health and safety overview. Avoid low-level debug/configuration dumps and explain unavailable capabilities in plain language.
6. **Interaction quality:** keyboard-accessible controls, responsive layouts, loading skeletons, empty states, retry affordances, clear focus states, and useful status announcements.

## Implementation approach

- First map the current views, API contracts, and existing styles. Preserve existing routes and backend contracts.
- Implement the redesign in the existing React/TypeScript frontend; do not invent backend capabilities or authentication.
- Use the current data APIs and existing safety settings. Do not change database contents, connection configuration, or target execution.
- Keep the schema fingerprint available only as a secondary technical detail (for example, a copyable/expandable “Schema fingerprint” section), rather than the main page content.
- Avoid adding a large UI dependency unless the existing stack cannot support the required interactions.

## Acceptance criteria

- A first-time user can identify the next step without seeing raw API routes or infrastructure details.
- Schema metadata is available for the selected source but is not dumped all at once; details are searchable and collapsible.
- No secrets or database connection details are rendered.
- Existing routes, API contracts, and migration safety controls continue to work.
- Main screens are responsive and keyboard navigable, with understandable loading, empty, success, and error states.
- Frontend tests and production build pass after implementation.

## Open product choice

Should detailed schema metadata be available to every signed-in user, or should the schema browser be limited to a database-admin role? Authentication is currently unavailable, so the implementation should treat the current frontend as a single-user local development console and avoid implying role-based privacy controls.
