# Creator Locked Modules V1 Architecture

## Objective

Allow a creator to mark a `Canopy Module` as access-controlled without turning Canopy into a generic software marketplace or exposing payment credentials to module code.

## Recommended Narrow V1

Implement only host-enforced module entitlements.

That means:
- the module remains a normal source-bound module bundle;
- the host checks entitlement before loading it;
- the module receives only a bounded entitlement state;
- the module never sees raw payment credentials or reusable unlock secrets; and
- unauthorized viewers can still see the source item and a locked preview state.

## V1 architecture

### 1. New manifest-level fields

Suggested fields for module-associated metadata:
- `module_access_policy`
- `creator_id`
- `entitlement_required`
- `entitlement_scope`
- `allowed_actor_types`
- `entitlement_class`
- `entitlement_verifier`
- `bundle_ciphertext_ref`
- `locked_preview_ref`

### 2. Actor-scoped entitlement record

Suggested local record shape:
- `entitlement_id`
- `actor_id`
- `module_asset_id`
- `creator_id`
- `scope`
- `status` (`active`, `trial`, `expired`, `revoked`)
- `issued_at`
- `expires_at`
- `proof_ref`

This record should remain local-first and private by default.

Representative entitlement classes:
- `purchased_access`
- `subscription_access`
- `classroom_access`
- `org_access`
- `creator_grant`
- `developer_agent`

### 3. Load path

Recommended runtime sequence:
1. source item renders normally
2. deck or source attempts to open module
3. host checks `module_access_policy`
4. host verifies local entitlement or bounded remote proof, including any developer-agent or creator-granted evaluator class
5. if authorized, host loads module through the existing sandboxed runtime
6. if unauthorized, host renders locked-preview state or access-request CTA

### 4. Security constraints

Do not allow:
- raw payment-card data inside module code
- reusable unlock secrets inside module code
- module-controlled entitlement verification
- ambient access to wallet, billing, or purchase state

Entitlement verification should occur in trusted host code only.

### 5. Stronger later option

If stronger creator protection is needed later:
- store the module attachment encrypted at rest;
- decrypt locally only after entitlement verification; and
- keep decryption material outside module JavaScript.

That is more work and should not be V1 unless creator-controlled distribution becomes urgent.

## UX recommendation

Visible states:
- `Open module`
- `Locked preview`
- `Request access`
- `Unlock`
- `Expired`

This should feel like a first-class Canopy surface, not a bolted-on paywall.

## Implementation difficulty

### Narrow V1
Moderate.

Main work:
- entitlement metadata
- host-side verification path
- locked-preview rendering
- actor-scoped local entitlement store
- API for entitlement inspection / grant / revoke

### Stronger encrypted-bundle variant
Higher.

Main additional work:
- encrypted attachment handling
- local unsealing path
- key lifecycle and revocation semantics
- offline entitlement edge cases

## Recommendation

Do not build payments first.

If this is ever implemented, start with:
- creator-controlled host gating
- manual or signed entitlement grants
- locked-preview states
- no payment vault inside the module runtime

That gives the product value and patent embodiment density without dragging in a full commerce stack.
