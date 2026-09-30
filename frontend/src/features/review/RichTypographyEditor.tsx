import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Extension, Mark, mergeAttributes } from "@tiptap/core";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  IndentDecrease,
  IndentIncrease,
  Italic,
  Link2,
  List,
  ListOrdered,
  Underline,
} from "lucide-react";
import { SuperscriptMarkerControl, type MarkerPlacement } from "../../components/SuperscriptMarkerControl";
import { useLocale } from "../../i18n";
import {
  TYPOGRAPHY_LIMITS,
  type ReviewTextAlign,
  type TextStyle,
} from "./reviewPresentation";

const TEXT_ALIGNMENTS: Array<{ value: ReviewTextAlign; icon: typeof AlignLeft; key: "alignLeft" | "alignCenter" | "alignRight" | "justify" }> = [
  { value: "left", icon: AlignLeft, key: "alignLeft" },
  { value: "center", icon: AlignCenter, key: "alignCenter" },
  { value: "right", icon: AlignRight, key: "alignRight" },
  { value: "justify", icon: AlignJustify, key: "justify" },
];

const BUNDLED_FONTS = ["Carlito", "Calibri", "Noto Sans CJK SC", "Noto Sans CJK TC", "Noto Sans CJK HK"];
const SAFE_FONT_FAMILY = /^[\p{L}\p{N}\s.,'_+()&\/-]+$/u;
const HEX_COLOR = /^#[0-9a-f]{6}$/i;
const MAX_INDENT_LEVEL = 6;

function safeFontFamily(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed && trimmed.length <= 100 && SAFE_FONT_FAMILY.test(trimmed) ? trimmed : null;
}

function bounded(value: unknown, min: number, max: number): number | null {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) && number >= min && number <= max ? number : null;
}

function indentLevel(value: unknown): number {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isInteger(number) && number >= 0 && number <= MAX_INDENT_LEVEL ? number : 0;
}

function generatedStyle(attributes: Record<string, unknown>, paragraph = false): string {
  const declarations: string[] = [];
  const family = safeFontFamily(attributes.fontFamily);
  const size = bounded(attributes.fontSizePt, TYPOGRAPHY_LIMITS.fontSize.min, TYPOGRAPHY_LIMITS.fontSize.max);
  const color = typeof attributes.color === "string" && HEX_COLOR.test(attributes.color) ? attributes.color : null;
  if (family) declarations.push(`font-family: "${family}", Carlito, sans-serif`);
  if (size !== null) declarations.push(`font-size: ${size}pt`);
  if (color) declarations.push(`color: ${color}`);
  if (paragraph) {
    const lineHeight = bounded(attributes.lineHeight, TYPOGRAPHY_LIMITS.lineHeight.min, TYPOGRAPHY_LIMITS.lineHeight.max);
    const before = bounded(attributes.spaceBeforePt, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max);
    const after = bounded(attributes.spaceAfterPt, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max);
    const textAlign = TEXT_ALIGNMENTS.some(({ value }) => value === attributes.textAlign) ? attributes.textAlign : null;
    if (lineHeight !== null) declarations.push(`line-height: ${lineHeight}`);
    if (before !== null) declarations.push(`margin-top: ${before}pt`);
    if (after !== null) declarations.push(`margin-bottom: ${after}pt`);
    if (textAlign) declarations.push(`text-align: ${textAlign}`);
  }
  return declarations.join("; ");
}

const InlineTextStyle = Mark.create({
  name: "inlineTextStyle",
  addAttributes() {
    return {
      fontFamily: { default: null, parseHTML: (element) => element.getAttribute("data-font-family") },
      fontSizePt: { default: null, parseHTML: (element) => element.getAttribute("data-font-size-pt") },
      color: { default: null, parseHTML: (element) => element.getAttribute("data-color") },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-font-family], span[data-font-size-pt], span[data-color]" }];
  },
  renderHTML({ HTMLAttributes }) {
    const attributes: Record<string, string> = {};
    const family = safeFontFamily(HTMLAttributes.fontFamily);
    const size = bounded(HTMLAttributes.fontSizePt, TYPOGRAPHY_LIMITS.fontSize.min, TYPOGRAPHY_LIMITS.fontSize.max);
    const color = typeof HTMLAttributes.color === "string" && HEX_COLOR.test(HTMLAttributes.color) ? HTMLAttributes.color.toUpperCase() : null;
    if (family) attributes["data-font-family"] = family;
    if (size !== null) attributes["data-font-size-pt"] = String(size);
    if (color) attributes["data-color"] = color;
    const style = generatedStyle(HTMLAttributes);
    return ["span", mergeAttributes(attributes, style ? { style } : {}), 0];
  },
});

const ParagraphStyle = Extension.create({
  name: "paragraphStyle",
  addGlobalAttributes() {
    return [{
      types: ["paragraph", "listItem"],
      attributes: {
        lineHeight: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-line-height") ?? element.getAttribute("data-line-height-role"),
          renderHTML: (attributes) => {
            const value = bounded(attributes.lineHeight, TYPOGRAPHY_LIMITS.lineHeight.min, TYPOGRAPHY_LIMITS.lineHeight.max);
            return value === null ? {} : { "data-line-height": String(value), style: `line-height: ${value}` };
          },
        },
        spaceBeforePt: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-space-before-pt"),
          renderHTML: (attributes) => {
            const value = bounded(attributes.spaceBeforePt, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max);
            return value === null ? {} : { "data-space-before-pt": String(value), style: `margin-top: ${value}pt` };
          },
        },
        spaceAfterPt: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-space-after-pt"),
          renderHTML: (attributes) => {
            const value = bounded(attributes.spaceAfterPt, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max);
            return value === null ? {} : { "data-space-after-pt": String(value), style: `margin-bottom: ${value}pt` };
          },
        },
        textAlign: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-text-align"),
          renderHTML: (attributes) => TEXT_ALIGNMENTS.some(({ value }) => value === attributes.textAlign)
            ? { "data-text-align": attributes.textAlign, style: `text-align: ${attributes.textAlign}` }
            : {},
        },
        indentLevel: {
          default: null,
          parseHTML: (element) => indentLevel(element.getAttribute("data-indent-level")) || null,
          renderHTML: (attributes) => {
            const value = indentLevel(attributes.indentLevel);
            return value ? { "data-indent-level": String(value) } : {};
          },
        },
      },
    }];
  },
});

function cleanRichHtml(value: string): string {
  const document = new DOMParser().parseFromString(value, "text/html");
  document.body.querySelectorAll("[style]").forEach((node) => node.removeAttribute("style"));
  return document.body.innerHTML;
}

export function textStyleProperties(style: TextStyle): CSSProperties {
  return {
    "--report-font-family": `"${style.font_family}", Carlito, sans-serif`,
    "--report-font-size": `${style.font_size_pt}pt`,
    "--report-color": style.color,
    "--report-font-weight": style.bold ? "700" : "400",
    "--report-font-style": style.italic ? "italic" : "normal",
    "--report-text-decoration": style.underline ? "underline" : "none",
    "--report-line-height": String(style.line_height),
    "--report-space-before": `${style.space_before_pt}pt`,
    "--report-space-after": `${style.space_after_pt}pt`,
    "--report-text-align": style.text_align,
    "--report-indent": `${(style.indent_level ?? 0) * 2}em`,
  } as CSSProperties;
}

export function BoundedNumberInput({
  label,
  value,
  min,
  max,
  step,
  disabled,
  onCommit,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled: boolean;
  onCommit: (value: number) => void;
}) {
  const { t } = useLocale();
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const parsed = bounded(draft, min, max);
  const invalid = parsed === null;
  return <label className="precise-number-field">
    <span>{label}</span>
    <input
      aria-label={label}
      aria-invalid={invalid}
      type="number"
      min={min}
      max={max}
      step={step}
      value={draft}
      disabled={disabled}
      onChange={(event) => {
        const next = event.target.value;
        setDraft(next);
        const valid = bounded(next, min, max);
        if (valid !== null) onCommit(valid);
      }}
      onBlur={() => { if (invalid) setDraft(String(value)); }}
    />
    {invalid && <small role="alert">{t("numberRange", { min, max })}</small>}
  </label>;
}

function FontFamilyInput({ label, value, disabled, onCommit }: { label: string; value: string; disabled: boolean; onCommit: (value: string) => void }) {
  const { t } = useLocale();
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const valid = safeFontFamily(draft);
  const bundled = BUNDLED_FONTS.some((font) => font.toLocaleLowerCase() === draft.trim().toLocaleLowerCase());
  return <label className="font-family-field">
    <span>{label}</span>
    <input
      aria-label={label}
      aria-invalid={!valid}
      list="report-bundled-fonts"
      maxLength={100}
      value={draft}
      disabled={disabled}
      onChange={(event) => {
        const next = event.target.value;
        setDraft(next);
        const safe = safeFontFamily(next);
        if (safe) onCommit(safe);
      }}
      onBlur={() => { if (!valid) setDraft(value); }}
    />
    {!valid
      ? <small role="alert">{t("invalidFontFamily")}</small>
      : !bundled && <small className="font-warning">{t("fontFallbackWarning")}</small>}
  </label>;
}

export function TextStyleControls({
  idPrefix,
  value,
  disabled,
  onChange,
  showParagraph = true,
  showParagraphSpacing = true,
  showIndent = false,
  compact = false,
}: {
  idPrefix: string;
  value: TextStyle;
  disabled: boolean;
  onChange: (change: Partial<TextStyle>) => void;
  showParagraph?: boolean;
  showParagraphSpacing?: boolean;
  showIndent?: boolean;
  compact?: boolean;
}) {
  const { t } = useLocale();
  return <div className={`precise-typography-controls${compact ? " compact" : ""}`}>
    <datalist id="report-bundled-fonts">{BUNDLED_FONTS.map((font) => <option key={font} value={font} />)}</datalist>
    <FontFamilyInput label={`${idPrefix} ${t("fontFamily")}`} value={value.font_family} disabled={disabled} onCommit={(font_family) => onChange({ font_family })} />
    <BoundedNumberInput label={`${idPrefix} ${t("fontSize")}`} value={value.font_size_pt} {...TYPOGRAPHY_LIMITS.fontSize} disabled={disabled} onCommit={(font_size_pt) => onChange({ font_size_pt })} />
    <label className="color-field"><span>{t("fontColor")}</span><input aria-label={`${idPrefix} ${t("fontColor")}`} type="color" value={value.color} disabled={disabled} onChange={(event) => onChange({ color: event.target.value.toUpperCase() })} /></label>
    <div className="typography-toggle-group" role="group" aria-label={`${idPrefix} ${t("textFormatting")}`}>
      <button type="button" className="icon-button" aria-label={`${idPrefix} ${t("bold")}`} aria-pressed={value.bold} disabled={disabled} onClick={() => onChange({ bold: !value.bold })}><Bold size={15} /></button>
      <button type="button" className="icon-button" aria-label={`${idPrefix} ${t("italic")}`} aria-pressed={value.italic} disabled={disabled} onClick={() => onChange({ italic: !value.italic })}><Italic size={15} /></button>
      <button type="button" className="icon-button" aria-label={`${idPrefix} ${t("underline")}`} aria-pressed={value.underline} disabled={disabled} onClick={() => onChange({ underline: !value.underline })}><Underline size={15} /></button>
    </div>
    {showParagraph && <>
      <BoundedNumberInput label={`${idPrefix} ${t("lineHeight")}`} value={value.line_height} {...TYPOGRAPHY_LIMITS.lineHeight} disabled={disabled} onCommit={(line_height) => onChange({ line_height })} />
      {showParagraphSpacing && <>
        <BoundedNumberInput label={`${idPrefix} ${t("spaceBefore")}`} value={value.space_before_pt} {...TYPOGRAPHY_LIMITS.spacing} disabled={disabled} onCommit={(space_before_pt) => onChange({ space_before_pt })} />
        <BoundedNumberInput label={`${idPrefix} ${t("spaceAfter")}`} value={value.space_after_pt} {...TYPOGRAPHY_LIMITS.spacing} disabled={disabled} onCommit={(space_after_pt) => onChange({ space_after_pt })} />
      </>}
      {showIndent && <BoundedNumberInput label={`${idPrefix} ${t("indentLevel")}`} value={value.indent_level ?? 0} {...TYPOGRAPHY_LIMITS.indent} disabled={disabled} onCommit={(indent_level) => onChange({ indent_level })} />}
      <label><span>{t("alignment")}</span><select aria-label={`${idPrefix} ${t("alignment")}`} disabled={disabled} value={value.text_align} onChange={(event) => onChange({ text_align: event.target.value as ReviewTextAlign })}>{TEXT_ALIGNMENTS.map(({ value: alignment, key }) => <option key={alignment} value={alignment}>{t(key)}</option>)}</select></label>
    </>}
  </div>;
}

export function RichTypographyEditor({
  label,
  value,
  defaultStyle,
  disabled,
  showAdvanced = false,
  onChange,
  onDefaultStyleChange,
}: {
  label: string;
  value: string;
  defaultStyle: TextStyle;
  disabled: boolean;
  showAdvanced?: boolean;
  onChange: (value: string) => void;
  onDefaultStyleChange: (change: Partial<TextStyle>) => void;
}) {
  const { t } = useLocale();
  const [, setSelectionRevision] = useState(0);
  const editor = useEditor({
    extensions: [StarterKit.configure({ link: { openOnClick: false } }), InlineTextStyle, ParagraphStyle],
    content: value,
    editable: !disabled,
    onSelectionUpdate: () => setSelectionRevision((revision) => revision + 1),
    onUpdate: ({ editor: activeEditor }) => onChange(cleanRichHtml(activeEditor.getHTML())),
  });
  useEffect(() => { editor?.setEditable(!disabled); }, [disabled, editor]);
  useEffect(() => {
    if (editor && cleanRichHtml(editor.getHTML()) !== value) editor.commands.setContent(value);
  }, [editor, value]);

  const hasSelection = editor ? !editor.state.selection.empty : false;
  const inlineAttributes = editor?.getAttributes("inlineTextStyle") ?? {};
  const activeNode = editor?.isActive("listItem") ? "listItem" : "paragraph";
  const paragraphAttributes = editor?.getAttributes(activeNode) ?? {};
  const activeIndentLevel = indentLevel(paragraphAttributes.indentLevel);
  const activeStyle = useMemo<TextStyle>(() => ({
    ...defaultStyle,
    ...(hasSelection ? {
      font_family: safeFontFamily(inlineAttributes.fontFamily) ?? defaultStyle.font_family,
      font_size_pt: bounded(inlineAttributes.fontSizePt, TYPOGRAPHY_LIMITS.fontSize.min, TYPOGRAPHY_LIMITS.fontSize.max) ?? defaultStyle.font_size_pt,
      color: typeof inlineAttributes.color === "string" && HEX_COLOR.test(inlineAttributes.color) ? inlineAttributes.color.toUpperCase() : defaultStyle.color,
      bold: editor?.isActive("bold") ?? defaultStyle.bold,
      italic: editor?.isActive("italic") ?? defaultStyle.italic,
      underline: editor?.isActive("underline") ?? defaultStyle.underline,
    } : {}),
    line_height: bounded(paragraphAttributes.lineHeight, TYPOGRAPHY_LIMITS.lineHeight.min, TYPOGRAPHY_LIMITS.lineHeight.max) ?? defaultStyle.line_height,
    space_before_pt: bounded(paragraphAttributes.spaceBeforePt, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max) ?? defaultStyle.space_before_pt,
    space_after_pt: bounded(paragraphAttributes.spaceAfterPt, TYPOGRAPHY_LIMITS.spacing.min, TYPOGRAPHY_LIMITS.spacing.max) ?? defaultStyle.space_after_pt,
    text_align: TEXT_ALIGNMENTS.some(({ value: alignment }) => alignment === paragraphAttributes.textAlign) ? paragraphAttributes.textAlign as ReviewTextAlign : defaultStyle.text_align,
    indent_level: hasSelection ? activeIndentLevel : defaultStyle.indent_level ?? 0,
  }), [defaultStyle, editor, hasSelection, inlineAttributes, paragraphAttributes]);

  const updateStyle = (change: Partial<TextStyle>) => {
    if (!editor) return;
    if (!hasSelection) {
      onDefaultStyleChange(change);
      return;
    }
    const paragraphChange: Record<string, unknown> = {};
    if (change.line_height !== undefined) paragraphChange.lineHeight = change.line_height;
    if (change.space_before_pt !== undefined) paragraphChange.spaceBeforePt = change.space_before_pt;
    if (change.space_after_pt !== undefined) paragraphChange.spaceAfterPt = change.space_after_pt;
    if (change.text_align !== undefined) paragraphChange.textAlign = change.text_align;
    if (change.indent_level !== undefined) paragraphChange.indentLevel = change.indent_level || null;
    if (Object.keys(paragraphChange).length) editor.chain().focus().updateAttributes(activeNode, paragraphChange).run();

    const inlineChange = Object.fromEntries(Object.entries(change).filter(([key]) => ["font_family", "font_size_pt", "color", "bold", "italic", "underline"].includes(key)));
    if (!Object.keys(inlineChange).length) return;
    let chain = editor.chain().focus();
    const markAttributes: Record<string, unknown> = {};
    if (change.font_family !== undefined) markAttributes.fontFamily = change.font_family;
    if (change.font_size_pt !== undefined) markAttributes.fontSizePt = change.font_size_pt;
    if (change.color !== undefined) markAttributes.color = change.color;
    if (Object.keys(markAttributes).length) chain = chain.setMark("inlineTextStyle", markAttributes);
    if (change.bold !== undefined && change.bold !== editor.isActive("bold")) chain = chain.toggleBold();
    if (change.italic !== undefined && change.italic !== editor.isActive("italic")) chain = chain.toggleItalic();
    if (change.underline !== undefined && change.underline !== editor.isActive("underline")) chain = chain.toggleUnderline();
    chain.run();
  };

  const insertFootnoteMarker = (marker: string, placement: MarkerPlacement) => {
    if (!editor || disabled) return;
    const { from, to, empty } = editor.state.selection;
    const at = placement === "before" ? from : to;
    let chain = editor.chain().focus().insertContentAt(at, marker);
    if (empty) {
      chain = chain.setTextSelection(at + marker.length);
    } else if (placement === "before") {
      chain = chain.setTextSelection({ from: from + marker.length, to: to + marker.length });
    } else {
      chain = chain.setTextSelection({ from, to });
    }
    chain.run();
  };

  const changeIndent = (change: -1 | 1) => {
    if (!editor || disabled) return;
    const next = Math.max(0, Math.min(MAX_INDENT_LEVEL, activeIndentLevel + change));
    editor.chain().focus().updateAttributes(
      activeNode,
      { indentLevel: next || null },
    ).run();
  };

  return <>
    <div className="rich-toolbar" aria-label={t("textFormatting")} onClick={(event) => event.stopPropagation()}>
      <button type="button" className="icon-button" title={t("bold")} aria-pressed={activeStyle.bold} disabled={disabled} onClick={() => updateStyle({ bold: !activeStyle.bold })}><Bold size={15} /></button>
      <button type="button" className="icon-button" title={t("italic")} aria-pressed={activeStyle.italic} disabled={disabled} onClick={() => updateStyle({ italic: !activeStyle.italic })}><Italic size={15} /></button>
      <button type="button" className="icon-button" title={t("underline")} aria-pressed={activeStyle.underline} disabled={disabled} onClick={() => updateStyle({ underline: !activeStyle.underline })}><Underline size={15} /></button>
      <button type="button" className="icon-button" title={t("bulletList")} aria-pressed={editor?.isActive("bulletList") ?? false} disabled={disabled} onClick={() => editor?.chain().focus().toggleBulletList().run()}><List size={15} /></button>
      <button type="button" className="icon-button" title={t("numberedList")} aria-pressed={editor?.isActive("orderedList") ?? false} disabled={disabled} onClick={() => editor?.chain().focus().toggleOrderedList().run()}><ListOrdered size={15} /></button>
      <button type="button" className="icon-button" title={t("decreaseIndent")} disabled={disabled || activeIndentLevel === 0} onClick={() => changeIndent(-1)}><IndentDecrease size={15} /></button>
      <button type="button" className="icon-button" title={t("increaseIndent")} disabled={disabled || activeIndentLevel === MAX_INDENT_LEVEL} onClick={() => changeIndent(1)}><IndentIncrease size={15} /></button>
      <button type="button" className="icon-button" title={t("addLink")} disabled={disabled} onClick={() => { const href = window.prompt(t("linkUrl")); if (href) editor?.chain().focus().setLink({ href }).run(); }}><Link2 size={15} /></button>
      <span className="selection-scope">{t(hasSelection ? "selectedText" : "moduleDefault")}</span>
      {TEXT_ALIGNMENTS.map(({ value: alignment, icon: Icon, key }) => <button type="button" key={alignment} className="icon-button" title={t(key)} aria-pressed={activeStyle.text_align === alignment} disabled={disabled} onClick={() => updateStyle({ text_align: alignment })}><Icon size={15} /></button>)}
      <SuperscriptMarkerControl disabled={disabled} onInsert={insertFootnoteMarker} />
    </div>
    {showAdvanced && <div className="advanced-typography-controls" onClick={(event) => event.stopPropagation()}>
      <TextStyleControls idPrefix={label} value={activeStyle} disabled={disabled} showIndent onChange={updateStyle} />
    </div>}
    <EditorContent editor={editor} className="review-rich-text" style={textStyleProperties(defaultStyle)} />
  </>;
}
