"""Low-allocation semantic reconciliation hot path for the IMS import runtime.

The base ``WorkbookSemanticReconciler`` owns all business semantics.  This subclass
only compiles per-column metadata once and scans pandas rows as tuples so the same
semantic observations are produced without repeated ``DataFrame.iloc`` access and
without recomputing invariant column context for every numeric cell.
"""
from __future__ import annotations

from app.services.workbook_semantic_reconciliation import WorkbookSemanticReconciler


class CompiledWorkbookSemanticReconciler(WorkbookSemanticReconciler):
    """Semantically identical observation discovery with a compiled column plan."""

    def _row_key_from_values(self, values, dimension_columns):
        parts = []
        for column in dimension_columns:
            if column >= len(values):
                continue
            value = self._norm(values[column])
            if value and value not in {"NAN", "NONE"}:
                parts.append(value)
        return tuple(parts)

    def _column_plan(self, frame, matrix, dimension_columns, sheet_type):
        dimensions = set(dimension_columns)
        plan = []
        for column in range(frame.shape[1]):
            if column in dimensions:
                continue
            raw_parts, carried_parts = self._column_context(matrix, column)
            metric_family = self._metric_family(raw_parts, carried_parts)
            if metric_family is None:
                continue
            plan.append(
                (
                    column,
                    metric_family,
                    self._phase(raw_parts, carried_parts),
                    self._period_scope(raw_parts, carried_parts, sheet_type),
                    self._product_key(raw_parts, carried_parts),
                )
            )
        return plan

    def _observations(self):
        observations, profiles = [], {}
        for sheet_name, frame in self.workbook.items():
            item = self._manifest_by_name.get(str(sheet_name), {})
            if item.get("coverage") in {"unclassified", "explicit_nondata"}:
                continue
            sheet_type = item.get("sheet_type")
            header_row = self._header_row(sheet_name, frame)
            matrix = self._header_matrix(frame, header_row)
            dimensions = self._dimension_columns(frame, header_row, matrix)
            pivot_candidate = self._is_pivot_candidate(frame, sheet_type)
            profiles[str(sheet_name)] = {
                "pivot_candidate": pivot_candidate,
                "header_row": header_row,
                "dimension_columns": dimensions,
            }

            column_plan = self._column_plan(frame, matrix, dimensions, sheet_type)
            if not column_plan:
                continue

            source_rows = frame.iloc[header_row + 1 :]
            for row_index, values in enumerate(
                source_rows.itertuples(index=False, name=None),
                start=header_row + 1,
            ):
                row_key = self._row_key_from_values(values, dimensions)
                if not row_key:
                    continue
                for column, metric_family, phase, period_scope, product_key in column_plan:
                    if column >= len(values):
                        continue
                    value = self._number(values[column])
                    if value is None:
                        continue
                    observation = {
                        "sheet_name": str(sheet_name),
                        "row": row_index + 1,
                        "column": column + 1,
                        "value": value,
                        "row_key": row_key,
                        "metric_family": metric_family,
                        "phase": phase,
                        "period_scope": period_scope,
                        "product_key": product_key,
                        "pivot_candidate": pivot_candidate,
                    }
                    observation["semantic_key"] = (
                        observation["row_key"],
                        observation["metric_family"],
                        observation["phase"],
                        observation["period_scope"],
                        observation["product_key"],
                    )
                    observations.append(observation)
        return observations, profiles
