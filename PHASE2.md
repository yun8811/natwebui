# Phase 2 Development Constraints

## Goal

Phase 2 focuses on four areas:

1. UI cleanup
   - Replace text-heavy action buttons with symbolic icon buttons
   - Unify font family, font size, line height, button size, and spacing
2. VLESS chain proxy MVP
   - Support only `VLESS + Reality -> VLESS + Reality`
   - Support only nodes already deployed and managed by this panel
   - Do not support external backend links or manually pasted upstream nodes
3. Preserve existing direct nodes
   - Front node and backend node must remain usable as their original direct nodes
   - Creating a chain node must not overwrite or mutate the original direct-node semantics
4. Defer HY2
   - HY2 support is not part of this phase
   - HY2 direct support and HY2 chain support are explicitly postponed

## Explicit Non-Goals

Phase 2 must NOT include:

- HY2 deployment support
- HY2 chain proxy support
- Arbitrary mixed-protocol chains
- External backend nodes not created by this panel
- Multi-hop chains beyond one front node + one backend node
- Broad refactors unrelated to chain proxy or current UI cleanup

## Chain Proxy Definition

The chain proxy in Phase 2 is a true two-layer VLESS chain:

- Client connects to front node A
- Front node A decrypts the first-layer VLESS traffic
- Front node A re-encodes and forwards traffic to backend node B using a second-layer VLESS outbound
- Backend node B decrypts and exits to the destination

This is NOT a pure TCP relay design.

## Front Node Reuse Model

Preferred implementation model for Phase 2:

- Reuse the existing front node VLESS Reality inbound port
- Do NOT require a new front-node public port in the MVP if same-port multi-user routing is workable
- Add a dedicated chain user on the existing front-node inbound
- Add a dedicated outbound on the front node that points to backend node B
- Add a route rule on the front node that matches the chain user and sends it to backend B

Routing should distinguish:

- Existing direct users on front node A -> original direct outbound behavior
- Chain-specific user on front node A -> backend B outbound behavior

## Data Model Constraints

A chain node is a new logical node record and must not overwrite the original node records.

Expected properties of a chain node:

- It is created from one front node and one backend node
- It should be visually identifiable as a chain node in the list and detail page
- It should preserve references to:
  - `front_node_id`
  - `backend_node_id`
  - chain mode/type metadata
- It should generate its own client-facing import link
- The client-facing link should point to the front node entry
- The backend node parameters should be used internally for the second hop, not exposed as the final endpoint address

## Deployment Constraints

All chain deployment logic must be incremental and targeted.

Required safety behavior:

- Only add the exact chain user / outbound / route needed
- Do not destroy or replace unrelated front-node config
- Do not break existing direct-node usability on front node A
- Deleting or rebuilding one chain node must only affect that chain node’s own config fragments
- Reinstall behavior must remain scoped and reversible

If the real active config structure makes precise in-place mutation too risky, stop and discuss before broad rewrite.

## Supported Scope in Phase 2 MVP

Phase 2 chain MVP supports only:

- Front node: panel-managed, already deployed, `VLESS + Reality`
- Backend node: panel-managed, already deployed, `VLESS + Reality`
- One front + one backend per chain node
- UI creation flow from existing node list

## UI Constraints

UI cleanup in this phase should follow these rules:

- Replace text action buttons with symbolic icon buttons
- Keep hover tooltip text for clarity
- Add a chain indicator icon for chain-derived nodes
- Unify font family across list, detail, forms, and action areas
- Unify font size and line height for denser, cleaner layout
- Keep the page visually cleaner and less noisy than Phase 1

## Decision Policy

If implementation reaches uncertainty on same-port chain routing, safe config mutation, or client-link semantics:

- pause at the narrow decision point
- discuss with the user before expanding scope

## Deliverable Order

Recommended execution order:

1. Write and keep this Phase 2 constraint file
2. UI icon/button cleanup + typography unification
3. Data model extension for chain nodes
4. Chain deployment implementation for VLESS -> VLESS
5. Verification with at least one real front node + backend node path
6. Git commit and push after verification
