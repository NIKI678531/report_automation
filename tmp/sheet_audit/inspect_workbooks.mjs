import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputs = [
  "C:/Users/nikili/Downloads/B_HSICSe Industry Code 1.xlsx",
  "C:/Users/nikili/Downloads/BBG-hstech constituent monthly update (version 1).xlsx",
];

for (const path of inputs) {
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
  process.stdout.write(`\n=== ${path} ===\n`);
  process.stdout.write((await wb.inspect({
    kind: "workbook,sheet,definedName,drawing",
    include: "id,name,range,formula,type,title",
    maxChars: 20000,
  })).ndjson + "\n");
  for (const sheet of wb.worksheets.items) {
    const used = sheet.getUsedRange();
    if (!used) continue;
    process.stdout.write(`\n--- SHEET ${sheet.name} USED ${used.address} ---\n`);
    process.stdout.write((await wb.inspect({
      kind: "table",
      sheetId: sheet.name,
      range: used.address,
      include: "values,formulas",
      tableMaxRows: 180,
      tableMaxCols: 40,
      tableMaxCellChars: 200,
      maxChars: 70000,
    })).ndjson + "\n");
    process.stdout.write((await wb.inspect({
      kind: "formula",
      sheetId: sheet.name,
      range: used.address,
      options: { maxResults: 1000 },
      maxChars: 70000,
    })).ndjson + "\n");
  }
}

const csvText = await fs.readFile("C:/Users/nikili/Downloads/HSTECH_eod_con_20260630.csv", "utf8");
const csvWb = await Workbook.fromCSV(csvText, { sheetName: "HSTECH" });
process.stdout.write("\n=== HSTECH_eod_con_20260630.csv ===\n");
process.stdout.write((await csvWb.inspect({ kind: "table", sheetId: "HSTECH", range: csvWb.worksheets.getItem("HSTECH").getUsedRange().address, include: "values", tableMaxRows: 100, tableMaxCols: 30, maxChars: 70000 })).ndjson + "\n");
