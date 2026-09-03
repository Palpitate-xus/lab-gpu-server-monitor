export function csvCell(value) {
  let text = value == null ? '' : String(value)
  // Spreadsheet applications may execute these prefixes as formulas. Leading
  // whitespace is included because some importers trim it before evaluation.
  if (/^[\s]*[=+\-@]/.test(text)) text = `'${text}`
  return `"${text.replaceAll('"', '""')}"`
}

export function csvRow(values) {
  return values.map(csvCell).join(',')
}
