/**
 * Universal data export helpers. Used by indicator detail page, and can be
 * reused by dashboard / country page / comparison view.
 */

export interface ExportRow {
  date: string;
  value: number;
}

export interface ExportMeta {
  filenameBase: string; // e.g. "inflation-cpi-de-destatis-SA"
  columnLabel: string;  // e.g. "Inflation (% YoY)"
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function exportCsv(rows: ExportRow[], meta: ExportMeta): void {
  const header = ["Date", meta.columnLabel].map(escapeCsv).join(",");
  const lines = [header];
  for (const r of rows) {
    lines.push([r.date, r.value.toString()].map(escapeCsv).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  triggerDownload(blob, `${meta.filenameBase}.csv`);
}

function escapeCsv(cell: string): string {
  if (/[",\n]/.test(cell)) {
    return `"${cell.replace(/"/g, '""')}"`;
  }
  return cell;
}

export async function exportXlsx(rows: ExportRow[], meta: ExportMeta): Promise<void> {
  // Dynamic import keeps xlsx out of the initial bundle (~400kb).
  const XLSX = await import("xlsx");
  const data = [
    ["Date", meta.columnLabel],
    ...rows.map((r) => [r.date, r.value]),
  ];
  const ws = XLSX.utils.aoa_to_sheet(data);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Data");
  const buf = XLSX.write(wb, { type: "array", bookType: "xlsx" });
  const blob = new Blob([buf], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  triggerDownload(blob, `${meta.filenameBase}.xlsx`);
}
