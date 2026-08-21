import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "../../outputs/hstech_monthly_data_request_20260819";
const outputPath = `${outputDir}/HSTECH_Monthly_Constituent_Data_Request.xlsx`;

const constituents = [
  ["981", "0981.HK", "SMIC", "中芯國際"],
  ["9999", "9999.HK", "NTES - S", "網易 - S"],
  ["700", "0700.HK", "TENCENT", "騰訊控股"],
  ["3690", "3690.HK", "MEITUAN - W", "美團 - W"],
  ["1211", "1211.HK", "BYD COMPANY", "比亞迪股份"],
  ["1810", "1810.HK", "XIAOMI - W", "小米集團 - W"],
  ["9988", "9988.HK", "BABA - W", "阿里巴巴 - W"],
  ["1347", "1347.HK", "HUA HONG GRACE", "華虹宏力"],
  ["9888", "9888.HK", "BIDU - SW", "百度集團 - SW"],
  ["9618", "9618.HK", "JD - SW", "京東集團 - SW"],
  ["992", "0992.HK", "LENOVO GROUP", "聯想集團"],
  ["1024", "1024.HK", "KUAISHOU - W", "快手 - W"],
  ["9961", "9961.HK", "TRIP.COM - S", "攜程集團 - S"],
  ["9868", "9868.HK", "XPENG - W", "小鵬集團 - W"],
  ["2015", "2015.HK", "LI AUTO - W", "理想汽車 - W"],
  ["300", "0300.HK", "MIDEA GROUP", "美的集團"],
  ["6690", "6690.HK", "HAIER SMARTHOME", "海爾智家"],
  ["9660", "9660.HK", "HORIZONROBOT - W", "地平線機器人 - W"],
  ["20", "0020.HK", "SENSETIME - W", "商湯 - W"],
  ["2382", "2382.HK", "SUNNY OPTICAL", "舜宇光學科技"],
  ["9626", "9626.HK", "BILIBILI - W", "嗶哩嗶哩 - W"],
  ["2513", "2513.HK", "KNOWLEDGE ATLAS", "智譜"],
  ["6618", "6618.HK", "JD HEALTH", "京東健康"],
  ["9863", "9863.HK", "LEAPMOTOR", "零跑汽車"],
  ["9866", "9866.HK", "NIO - SW", "蔚來 - SW"],
  ["241", "0241.HK", "ALI HEALTH", "阿里健康"],
  ["780", "0780.HK", "TONGCHENGTRAVEL", "同程旅行"],
  ["285", "0285.HK", "BYD ELECTRONIC", "比亞迪電子"],
  ["100", "0100.HK", "MINIMAX - W", "MINIMAX - W"],
  ["1698", "1698.HK", "TME - SW", "騰訊音樂 - SW"],
];

const headers = [
  "index_code", "as_of_date", "security_code", "ticker", "name_en", "name_zh_hant",
  "close_price", "currency", "weight_pct", "source_industry_code", "period_end",
  "period_start_1m", "return_1m_pct", "return_1m_missing_reason",
  "period_start_3m", "return_3m_pct", "return_3m_missing_reason",
  "period_start_6m", "return_6m_pct", "return_6m_missing_reason",
  "period_start_ytd", "return_ytd_pct", "return_ytd_missing_reason",
  "constituent_source", "return_source",
];

const fieldGuide = [
  ["index_code", "指数代码", "是", "文本", "HSTECH", "报告对应的成份股指数；整份文件必须一致。"],
  ["as_of_date", "月度数据截止日", "是", "日期 yyyy-mm-dd", "2026-06-30", "当月月末有效日期，必须属于报告月份且不晚于报告日。"],
  ["security_code", "股票代码", "是", "文本", "700", "港股本地代码；按文本保存，避免前导零和数字格式问题。"],
  ["ticker", "证券Ticker", "是", "文本", "0700.HK", "数据源使用的唯一证券标识；如供应商格式不同可在交付前统一。"],
  ["name_en", "股票英文名", "至少一种名称", "文本", "TENCENT", "报告优先展示的英文名称。"],
  ["name_zh_hant", "股票繁体中文名", "至少一种名称", "文本", "騰訊控股", "保留数据源原始繁体名称。"],
  ["close_price", "收市价", "是", "数值 > 0", "429.80", "截至as_of_date的收市价。"],
  ["currency", "价格币种", "是", "ISO币种", "HKD", "不得根据基金币种推测。"],
  ["weight_pct", "指数权重（%）", "是", "百分数数值", "8.30", "直接填8.30表示8.30%；全体权重应接近100。"],
  ["source_industry_code", "HSICS行业代码", "是", "文本", "70", "用于行业分类和后续图表计算。"],
  ["period_end", "回报截止日", "是", "日期 yyyy-mm-dd", "2026-06-30", "必须与as_of_date一致。"],
  ["period_start_1m", "1个月回报起始日", "是", "日期 yyyy-mm-dd", "2026-05-29", "填实际采用的交易日起点；所有股票应一致。"],
  ["return_1m_pct", "1个月总回报（%）", "数值或缺失原因", "百分数数值", "0.61", "Total Return口径；直接填0.61表示0.61%。"],
  ["return_1m_missing_reason", "1个月回报缺失原因", "条件必填", "文本", "INSUFFICIENT_HISTORY", "回报缺失时必填；有数值时必须留空。"],
  ["period_start_3m", "3个月回报起始日", "是", "日期 yyyy-mm-dd", "2026-03-31", "填实际采用的交易日起点；所有股票应一致。"],
  ["return_3m_pct", "3个月总回报（%）", "数值或缺失原因", "百分数数值", "-10.17", "Total Return口径。"],
  ["return_3m_missing_reason", "3个月回报缺失原因", "条件必填", "文本", "INSUFFICIENT_HISTORY", "回报缺失时必填；不可用0替代缺失值。"],
  ["period_start_6m", "6个月回报起始日", "是", "日期 yyyy-mm-dd", "2025-12-31", "填实际采用的交易日起点；所有股票应一致。"],
  ["return_6m_pct", "6个月总回报（%）", "数值或缺失原因", "百分数数值", "-27.41", "Total Return口径。"],
  ["return_6m_missing_reason", "6个月回报缺失原因", "条件必填", "文本", "INSUFFICIENT_HISTORY", "回报缺失时必填。"],
  ["period_start_ytd", "YTD回报起始日", "是", "日期 yyyy-mm-dd", "2025-12-31", "通常为上年末有效交易日，以数据源实际口径为准。"],
  ["return_ytd_pct", "YTD总回报（%）", "数值或缺失原因", "百分数数值", "-27.41", "年初至period_end的Total Return。"],
  ["return_ytd_missing_reason", "YTD回报缺失原因", "条件必填", "文本", "INSUFFICIENT_HISTORY", "回报缺失时必填。"],
  ["constituent_source", "成份股数据来源", "是", "文本", "Hang Seng Indexes", "整份文件应使用一个经确认的权威来源。"],
  ["return_source", "回报数据来源", "是", "文本", "Bloomberg", "整份文件应使用一个经确认的Total Return来源。"],
];

const colors = {
  navy: "#0B1F3A",
  teal: "#007A78",
  paleBlue: "#EAF3F8",
  paleYellow: "#FFF4CC",
  paleGreen: "#E7F3ED",
  paleGray: "#F4F7FA",
  border: "#D7DEE8",
  white: "#FFFFFF",
  black: "#000000",
  inputBlue: "#0000FF",
  warning: "#C62828",
};

const workbook = Workbook.create();
const dataSheet = workbook.worksheets.add("月度数据拉取清单");
const guideSheet = workbook.worksheets.add("字段说明");

dataSheet.showGridLines = false;
guideSheet.showGridLines = false;

// Main data request sheet.
dataSheet.getRange("A1:Y1").merge();
dataSheet.getRange("A1").values = [["The Performance of HSTECH Constituents — Monthly Data Request"]];
dataSheet.getRange("A1:Y1").format = {
  fill: colors.navy,
  font: { bold: true, color: colors.white, size: 16 },
  horizontalAlignment: "left",
  verticalAlignment: "center",
};

dataSheet.getRange("A2:Y2").merge();
dataSheet.getRange("A2").values = [["月度要求：每个报告月份提供一份完整的HSTECH成份股快照；黄色单元格由数据提供方填写，回报均采用Total Return百分数口径。当前名单为2026年6月项目样例，正式拉取前须按当月有效名单复核。"]];
dataSheet.getRange("A2:Y2").format = {
  fill: colors.paleBlue,
  font: { color: colors.navy, size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};

dataSheet.getRange("A4").values = [["报告月末日期"]];
dataSheet.getRange("B4").values = [[new Date(Date.UTC(2026, 5, 30))]];
dataSheet.getRange("D4").values = [["指数代码"]];
dataSheet.getRange("E4").values = [["HSTECH"]];
dataSheet.getRange("G4").values = [["数据频率"]];
dataSheet.getRange("H4").values = [["MONTHLY（月度）"]];
dataSheet.getRange("J4").values = [["成份股数量"]];
dataSheet.getRange("K4").formulas = [["=COUNTA(C7:C36)"]];

dataSheet.getRange("A5").values = [["成份股来源"]];
dataSheet.getRange("B5:C5").merge();
dataSheet.getRange("B5").values = [["Hang Seng Indexes Company Limited"]];
dataSheet.getRange("D5").values = [["回报来源"]];
dataSheet.getRange("E5:F5").merge();
dataSheet.getRange("E5").values = [["Bloomberg"]];
dataSheet.getRange("G5").values = [["回报口径"]];
dataSheet.getRange("H5:I5").merge();
dataSheet.getRange("H5").values = [["Total Return (%)"]];
dataSheet.getRange("J5").values = [["更新要求"]];
dataSheet.getRange("K5:Y5").merge();
dataSheet.getRange("K5").values = [["每月按当月月末有效HSTECH名单更新；不得沿用上月名单而不复核。"]];

dataSheet.getRange("A4:Y5").format = {
  font: { color: colors.black, size: 10 },
  verticalAlignment: "center",
};
dataSheet.getRange("A4:A5").format = { fill: colors.paleGray, font: { bold: true, color: colors.navy } };
dataSheet.getRange("D4:D5").format = { fill: colors.paleGray, font: { bold: true, color: colors.navy } };
dataSheet.getRange("G4:G5").format = { fill: colors.paleGray, font: { bold: true, color: colors.navy } };
dataSheet.getRange("J4:J5").format = { fill: colors.paleGray, font: { bold: true, color: colors.navy } };
dataSheet.getRange("B4").format = { fill: colors.paleYellow, font: { color: colors.inputBlue, bold: true }, numberFormat: "yyyy-mm-dd", horizontalAlignment: "center" };
dataSheet.getRange("E4").format = { fill: colors.paleYellow, font: { color: colors.inputBlue, bold: true }, horizontalAlignment: "center" };
dataSheet.getRange("B5:C5").format = { fill: colors.paleYellow, font: { color: colors.inputBlue } };
dataSheet.getRange("E5:F5").format = { fill: colors.paleYellow, font: { color: colors.inputBlue } };
dataSheet.getRange("H4:I5").format = { fill: colors.paleGreen, font: { bold: true, color: colors.teal }, horizontalAlignment: "center" };
dataSheet.getRange("K4").format = { fill: colors.paleGreen, font: { bold: true, color: colors.teal }, numberFormat: "0", horizontalAlignment: "center" };
dataSheet.getRange("K5:Y5").format = { fill: colors.paleBlue, font: { color: colors.navy }, wrapText: true };

dataSheet.getRange("A6:Y6").values = [headers];
dataSheet.getRange("A6:Y6").format = {
  fill: colors.teal,
  font: { bold: true, color: colors.white, size: 9 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { bottom: { style: "medium", color: colors.navy } },
};

const rows = constituents.map(([securityCode, ticker, nameEn, nameZh]) => [
  null, null, securityCode, ticker, nameEn, nameZh,
  null, "HKD", null, null, null,
  null, null, null, null, null, null, null, null, null, null, null, null,
  null, null,
]);
dataSheet.getRange("A7:Y36").values = rows;

for (let row = 7; row <= 36; row += 1) {
  dataSheet.getRange(`A${row}`).formulas = [["=$E$4"]];
  dataSheet.getRange(`B${row}`).formulas = [["=$B$4"]];
  dataSheet.getRange(`K${row}`).formulas = [["=$B$4"]];
  dataSheet.getRange(`X${row}`).formulas = [["=$B$5"]];
  dataSheet.getRange(`Y${row}`).formulas = [["=$E$5"]];
}

dataSheet.getRange("A7:Y36").format = {
  font: { color: colors.black, size: 9 },
  verticalAlignment: "center",
  borders: { insideHorizontal: { style: "thin", color: colors.border } },
};
dataSheet.getRange("A7:D36").format.horizontalAlignment = "center";
dataSheet.getRange("E7:F36").format.horizontalAlignment = "left";
dataSheet.getRange("G7:Y36").format.horizontalAlignment = "right";
dataSheet.getRange("B7:B36").format.numberFormat = "yyyy-mm-dd";
dataSheet.getRange("G7:G36").format.numberFormat = "0.00;[Red](0.00);-";
dataSheet.getRange("I7:I36").format.numberFormat = "0.00;[Red](0.00);-";
dataSheet.getRange("K7:L36").format.numberFormat = "yyyy-mm-dd";
dataSheet.getRange("O7:O36").format.numberFormat = "yyyy-mm-dd";
dataSheet.getRange("R7:R36").format.numberFormat = "yyyy-mm-dd";
dataSheet.getRange("U7:U36").format.numberFormat = "yyyy-mm-dd";
dataSheet.getRange("M7:M36").format.numberFormat = "0.00;[Red](0.00);-";
dataSheet.getRange("P7:P36").format.numberFormat = "0.00;[Red](0.00);-";
dataSheet.getRange("S7:S36").format.numberFormat = "0.00;[Red](0.00);-";
dataSheet.getRange("V7:V36").format.numberFormat = "0.00;[Red](0.00);-";

const editableRanges = ["G7:G36", "I7:J36", "L7:W36"];
for (const rangeAddress of editableRanges) {
  dataSheet.getRange(rangeAddress).format = {
    fill: colors.paleYellow,
    font: { color: colors.inputBlue, size: 9 },
  };
}
dataSheet.getRange("N7:N36").format.horizontalAlignment = "left";
dataSheet.getRange("Q7:Q36").format.horizontalAlignment = "left";
dataSheet.getRange("T7:T36").format.horizontalAlignment = "left";
dataSheet.getRange("W7:W36").format.horizontalAlignment = "left";

dataSheet.dataValidations.add({ range: "G7:G36", rule: { type: "decimal", operator: "between", formula1: 0.000001, formula2: 10000000 } });
dataSheet.dataValidations.add({ range: "I7:I36", rule: { type: "decimal", operator: "between", formula1: 0, formula2: 100 } });
for (const rangeAddress of ["M7:M36", "P7:P36", "S7:S36", "V7:V36"]) {
  dataSheet.dataValidations.add({ range: rangeAddress, rule: { type: "decimal", operator: "between", formula1: -10000, formula2: 10000 } });
}

const dataTable = dataSheet.tables.add("A6:Y36", true, "HSTECHMonthlyData");
dataTable.style = "TableStyleMedium2";
dataTable.showBandedColumns = false;
dataTable.showFilterButton = true;

dataSheet.getRange("A38:E38").merge();
dataSheet.getRange("A38").values = [["质量检查 / Quality Checks"]];
dataSheet.getRange("A38:E38").format = { fill: colors.navy, font: { bold: true, color: colors.white } };
dataSheet.getRange("A39:A40").values = [["Weight total (%)"], ["Numeric return cells"]];
dataSheet.getRange("B39").formulas = [["=SUM(I7:I36)"]];
dataSheet.getRange("B40").formulas = [["=COUNT(M7:M36)+COUNT(P7:P36)+COUNT(S7:S36)+COUNT(V7:V36)"]];
dataSheet.getRange("C39").formulas = [["=IF(ABS(B39-100)<=1,\"OK\",\"CHECK\")"]];
dataSheet.getRange("C40").formulas = [["=IF(B40>0,\"OK\",\"CHECK\")"]];
dataSheet.getRange("D39:E39").merge();
dataSheet.getRange("D40:E40").merge();
dataSheet.getRange("D39").values = [["目标：权重合计约100%（容差±1个百分点）"]];
dataSheet.getRange("D40").values = [["至少应提供一个有效的1M/3M/6M/YTD回报数值"]];
dataSheet.getRange("A39:E40").format = {
  fill: colors.paleGray,
  font: { color: colors.black, size: 9 },
  borders: { insideHorizontal: { style: "thin", color: colors.border } },
};
dataSheet.getRange("A39:A40").format.font = { bold: true, color: colors.navy };
dataSheet.getRange("B39").format.numberFormat = "0.00";
dataSheet.getRange("B39:C40").format.horizontalAlignment = "center";
dataSheet.getRange("C39:C40").conditionalFormats.add("containsText", { text: "OK", format: { fill: "#D9EAD3", font: { bold: true, color: "#2E7D32" } } });
dataSheet.getRange("C39:C40").conditionalFormats.add("containsText", { text: "CHECK", format: { fill: "#F4CCCC", font: { bold: true, color: colors.warning } } });

dataSheet.freezePanes.freezeRows(6);
dataSheet.freezePanes.freezeColumns(6);

const dataWidths = [14, 13, 13, 14, 22, 18, 13, 10, 13, 18, 13, 16, 15, 24, 16, 15, 24, 16, 15, 24, 16, 15, 24, 28, 22];
for (let col = 0; col < dataWidths.length; col += 1) {
  dataSheet.getRangeByIndexes(0, col, 40, 1).format.columnWidth = dataWidths[col];
}
dataSheet.getRange("A1:Y1").format.rowHeight = 34;
dataSheet.getRange("A2:Y2").format.rowHeight = 40;
dataSheet.getRange("A4:Y5").format.rowHeight = 26;
dataSheet.getRange("A6:Y6").format.rowHeight = 54;
dataSheet.getRange("A7:Y36").format.rowHeight = 23;
dataSheet.getRange("A38:E40").format.rowHeight = 24;

// Field guide sheet.
guideSheet.getRange("A1:F1").merge();
guideSheet.getRange("A1").values = [["HSTECH Monthly Constituent Data — 字段说明"]];
guideSheet.getRange("A1:F1").format = {
  fill: colors.navy,
  font: { bold: true, color: colors.white, size: 16 },
  verticalAlignment: "center",
};
guideSheet.getRange("A2:F2").merge();
guideSheet.getRange("A2").values = [["用途：供数据提供方逐只成份股拉取月末价格、权重以及1M/3M/6M/YTD总回报，并按标准CSV字段回填。"]];
guideSheet.getRange("A2:F2").format = { fill: colors.paleBlue, font: { color: colors.navy }, wrapText: true };

guideSheet.getRange("A4:F4").values = [["CSV字段名", "中文含义", "是否必填", "格式/单位", "示例", "拉取及校验说明"]];
guideSheet.getRange("A4:F4").format = {
  fill: colors.teal,
  font: { bold: true, color: colors.white },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
guideSheet.getRange("A5:F29").values = fieldGuide;
guideSheet.getRange("A5:F29").format = {
  font: { color: colors.black, size: 9 },
  verticalAlignment: "center",
  wrapText: true,
  borders: { insideHorizontal: { style: "thin", color: colors.border } },
};
guideSheet.getRange("A5:A29").format.font = { color: colors.navy, bold: true };
guideSheet.getRange("C5:E29").format.horizontalAlignment = "center";

guideSheet.getRange("A32:F32").merge();
guideSheet.getRange("A32").values = [["月度交付规则"]];
guideSheet.getRange("A32:F32").format = { fill: colors.navy, font: { bold: true, color: colors.white } };
const monthlyRules = [
  "每个报告月份交付一份完整数据文件，并按当月月末有效的HSTECH成份股名单重新复核。",
  "as_of_date与period_end必须相同，并且属于对应报告月份。",
  "1M、3M、6M及YTD回报必须使用相同的period_end，并记录各自实际period_start。",
  "weight_pct及各return_*_pct字段直接填写百分数，例如8.30代表8.30%，不得填写为0.083。",
  "个别回报因上市历史不足而缺失时可留空，但对应missing_reason必须填写；不得以0代替缺失值。",
  "同一股票代码只能出现一次；全体权重合计应接近100%。",
  "constituent_source和return_source在整份文件中分别保持一致。",
];
monthlyRules.forEach((rule, idx) => {
  const row = 33 + idx;
  guideSheet.getRange(`A${row}`).values = [[idx + 1]];
  guideSheet.getRange(`B${row}:F${row}`).merge();
  guideSheet.getRange(`B${row}`).values = [[rule]];
});
guideSheet.getRange("A33:F39").format = {
  fill: colors.paleGray,
  font: { color: colors.black, size: 10 },
  verticalAlignment: "center",
  wrapText: true,
  borders: { insideHorizontal: { style: "thin", color: colors.border } },
};
guideSheet.getRange("A33:A39").format = { fill: colors.paleGreen, font: { bold: true, color: colors.teal }, horizontalAlignment: "center" };

guideSheet.getRange("A42:F42").merge();
guideSheet.getRange("A42").values = [["名单基础：项目内2026-06 HSTECH样例快照；正式月度交付须以当月权威指数成份股名单为准。标准字段参考：docs/templates/constituent-performance-template.csv"]];
guideSheet.getRange("A42:F42").format = { fill: colors.paleYellow, font: { color: colors.navy, italic: true, size: 9 }, wrapText: true };

guideSheet.freezePanes.freezeRows(4);
const guideWidths = [28, 24, 15, 20, 22, 72];
for (let col = 0; col < guideWidths.length; col += 1) {
  guideSheet.getRangeByIndexes(0, col, 42, 1).format.columnWidth = guideWidths[col];
}
guideSheet.getRange("A1:F1").format.rowHeight = 34;
guideSheet.getRange("A2:F2").format.rowHeight = 36;
guideSheet.getRange("A4:F4").format.rowHeight = 32;
guideSheet.getRange("A5:F29").format.rowHeight = 36;
guideSheet.getRange("A32:F32").format.rowHeight = 26;
guideSheet.getRange("A33:F39").format.rowHeight = 32;
guideSheet.getRange("A42:F42").format.rowHeight = 38;

await fs.mkdir(outputDir, { recursive: true });

const dataInspect = await workbook.inspect({
  kind: "table",
  range: "月度数据拉取清单!A4:Y12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 25,
  maxChars: 9000,
});
console.log("DATA_INSPECT");
console.log(dataInspect.ndjson);

const guideInspect = await workbook.inspect({
  kind: "table",
  range: "字段说明!A1:F12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 6,
  maxChars: 6000,
});
console.log("GUIDE_INSPECT");
console.log(guideInspect.ndjson);

const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log("FORMULA_ERRORS");
console.log(formulaErrors.ndjson);

const dataPreview = await workbook.render({
  sheetName: "月度数据拉取清单",
  range: "A1:Y16",
  scale: 1,
  format: "png",
});
await fs.writeFile(`${outputDir}/data_preview.png`, new Uint8Array(await dataPreview.arrayBuffer()));

const dataLowerPreview = await workbook.render({
  sheetName: "月度数据拉取清单",
  range: "A28:Y40",
  scale: 1,
  format: "png",
});
await fs.writeFile(`${outputDir}/data_lower_preview.png`, new Uint8Array(await dataLowerPreview.arrayBuffer()));

const guidePreview = await workbook.render({
  sheetName: "字段说明",
  range: "A1:F42",
  scale: 1,
  format: "png",
});
await fs.writeFile(`${outputDir}/guide_preview.png`, new Uint8Array(await guidePreview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(`OUTPUT=${outputPath}`);
console.log(`DATA_PREVIEW=${outputDir}/data_preview.png`);
console.log(`GUIDE_PREVIEW=${outputDir}/guide_preview.png`);
