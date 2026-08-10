import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
const path = "C:/Users/nikili/Downloads/BBG-hstech constituent monthly update (version 1).xlsx";
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
process.stdout.write((await wb.inspect({kind:"sheet,definedName,drawing",include:"id,name,range,formula,type,title",maxChars:20000})).ndjson+"\n");
for (const sheet of wb.worksheets.items) {
  const used=sheet.getUsedRange();
  process.stdout.write(`\n===${sheet.name} ${used?.address}===\n`);
  if (!used) continue;
  process.stdout.write((await wb.inspect({kind:"table",sheetId:sheet.name,range:used.address,include:"values,formulas",tableMaxRows:60,tableMaxCols:12,tableMaxCellChars:160,maxChars:35000})).ndjson+"\n");
}
