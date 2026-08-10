import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load("C:/Users/nikili/Downloads/BBG-hstech constituent monthly update (version 1).xlsx"));
const s=wb.worksheets.getItem("Formula");
for (const r of ["A1:E8","A33:E36","G1:J8","M1:O36"]) {
  const x=s.getRange(r);
  process.stdout.write(`\n${r}\nVALUES ${JSON.stringify(x.values)}\nFORMULAS ${JSON.stringify(x.formulas)}\nDISPLAY ${JSON.stringify(x.displayFormulas)}\n`);
}
