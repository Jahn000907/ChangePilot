// ChangePilot Neo4j schema — constraints and indexes for the product / BOM graph.
//
// Source of truth: docs/changepilot_database_design_v0.4.md
//   sections 11.4 / 12.3 / 14.3 / 16.2 -> uniqueness constraints
//   section 22                          -> extra range indexes
//
// Every statement uses IF NOT EXISTS, so this file can be executed repeatedly.
// Only Community Edition compatible features are used: uniqueness constraints
// and range indexes. Node key, property existence and property type constraints
// are Enterprise-only and are deliberately absent; those rules are validated by
// the Python domain services instead (v0.4 sections 13, 15, 16, 19).
//
// Uniqueness constraints already provide the index used for uniqueness checks,
// so no additional index is created for the same property (v0.4 section 22).

// ---------------------------------------------------------------------------
// Part
// ---------------------------------------------------------------------------
CREATE CONSTRAINT part_id_unique IF NOT EXISTS
FOR (p:Part)
REQUIRE p.part_id IS UNIQUE;

CREATE CONSTRAINT part_number_unique IF NOT EXISTS
FOR (p:Part)
REQUIRE p.part_number IS UNIQUE;

// ---------------------------------------------------------------------------
// PartRevision
// ---------------------------------------------------------------------------
CREATE CONSTRAINT part_revision_id_unique IF NOT EXISTS
FOR (r:PartRevision)
REQUIRE r.revision_id IS UNIQUE;

CREATE CONSTRAINT part_revision_business_key_unique IF NOT EXISTS
FOR (r:PartRevision)
REQUIRE (r.part_number, r.revision_code) IS UNIQUE;

// ---------------------------------------------------------------------------
// BOMVersion
// ---------------------------------------------------------------------------
CREATE CONSTRAINT bom_version_id_unique IF NOT EXISTS
FOR (b:BOMVersion)
REQUIRE b.bom_version_id IS UNIQUE;

CREATE CONSTRAINT bom_code_unique IF NOT EXISTS
FOR (b:BOMVersion)
REQUIRE b.bom_code IS UNIQUE;

CREATE CONSTRAINT bom_version_business_key_unique IF NOT EXISTS
FOR (b:BOMVersion)
REQUIRE (
  b.parent_part_number,
  b.parent_revision_code,
  b.bom_revision_code
) IS UNIQUE;

// ---------------------------------------------------------------------------
// BOMLine
// ---------------------------------------------------------------------------
CREATE CONSTRAINT bom_line_id_unique IF NOT EXISTS
FOR (l:BOMLine)
REQUIRE l.bom_line_id IS UNIQUE;

// ---------------------------------------------------------------------------
// Extra range indexes (v0.4 section 22)
// ---------------------------------------------------------------------------
CREATE INDEX part_category_idx IF NOT EXISTS
FOR (p:Part)
ON (p.category);

CREATE INDEX part_type_idx IF NOT EXISTS
FOR (p:Part)
ON (p.part_type);

CREATE INDEX part_revision_state_idx IF NOT EXISTS
FOR (r:PartRevision)
ON (r.lifecycle_state);

CREATE INDEX bom_version_status_idx IF NOT EXISTS
FOR (b:BOMVersion)
ON (b.status);
