import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const root = process.cwd();
const currentFiles = (await fs.readdir(path.join(root, "data")))
  .filter((name) => /^Sifir_arac_\d{4}-\d{2}-\d{2}\.xlsx$/.test(name))
  .sort();
if (currentFiles.length !== 1) throw new Error(`Tek güncel Excel bekleniyordu: ${currentFiles.length}`);
const inputPath = path.join(root, "data", currentFiles[0]);
const outputDir = path.join(root, "..", "outputs", "01a00051-19b2-7d02-a6fe-799a19c8ee22");
await fs.mkdir(outputDir, { recursive: true });

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const prices = await workbook.inspect({
  kind: "table",
  range: "Guncel_Fiyatlar!A1:G8",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 7,
  maxChars: 6000,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});

for (const sheetName of ["Guncel_Fiyatlar"]) {
  const preview = await workbook.render({
    sheetName,
    range: "A1:G25",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(outputDir, `verify_${sheetName}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const outputPath = path.join(outputDir, currentFiles[0]);
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(prices.ndjson);
console.log(errors.ndjson);
console.log(outputPath);
