import { useEffect, useState } from "react";
import GridLayout, { WidthProvider, type Layout } from "react-grid-layout";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, GripVertical, Italic, Link2, List, Plus, Trash2 } from "lucide-react";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

const TwelveColumnGrid = WidthProvider(GridLayout);

export interface ReviewBlock {
  block_id: string;
  type: "rich_text" | "key_drivers" | "areas_to_monitor" | "outlook";
  title: string;
  content: string;
  x: number;
  y: number;
  w: number;
  h: number;
  text_align: ReviewTextAlign;
}

export type ReviewTextAlign = "left" | "center" | "right" | "justify";

const TEXT_ALIGNMENTS: Array<{ value: ReviewTextAlign; label: string; icon: typeof AlignLeft }> = [
  { value: "left", label: "Align left", icon: AlignLeft },
  { value: "center", label: "Align center", icon: AlignCenter },
  { value: "right", label: "Align right", icon: AlignRight },
  { value: "justify", label: "Justify", icon: AlignJustify },
];

function listHtml(rows: Array<Record<string, unknown>>): string {
  if (!rows.length) return "<p>No content yet.</p>";
  return `<ul>${rows.map((row) => `<li><strong>${String(row.title ?? "")}</strong><p>${String(row.body ?? "")}</p></li>`).join("")}</ul>`;
}

export function legacyReviewBlocks(review: Record<string, unknown>, reviewTitle = "Monthly summary"): ReviewBlock[] {
  const stored = Array.isArray(review.blocks) ? review.blocks as ReviewBlock[] : [];
  if (stored.length) return stored.map((block) => ({
    ...block,
    title: block.block_id === "summary" && block.title === "Monthly summary" ? reviewTitle : block.title,
    text_align: TEXT_ALIGNMENTS.some(({ value }) => value === block.text_align) ? block.text_align : "left",
  }));
  return [
    { block_id: "summary", type: "rich_text", title: reviewTitle, content: `<p>${String(review.summary ?? "")}</p>`, x: 0, y: 0, w: 12, h: 4, text_align: "left" },
    { block_id: "drivers", type: "key_drivers", title: "Key Drivers", content: listHtml(Array.isArray(review.drivers) ? review.drivers as Array<Record<string, unknown>> : []), x: 0, y: 4, w: 6, h: 7, text_align: "left" },
    { block_id: "monitor", type: "areas_to_monitor", title: "Key Areas to Monitor", content: listHtml(Array.isArray(review.monitor) ? review.monitor as Array<Record<string, unknown>> : []), x: 6, y: 4, w: 6, h: 5, text_align: "left" },
    { block_id: "outlook", type: "outlook", title: "Outlook", content: `<p>${String(review.outlook ?? "")}</p>`, x: 6, y: 9, w: 6, h: 4, text_align: "left" },
  ];
}

function RichTextBlock({ block, disabled, onChange, onTitleChange, onAlignmentChange, onDelete }: { block: ReviewBlock; disabled: boolean; onChange: (content: string) => void; onTitleChange: (title: string) => void; onAlignmentChange: (alignment: ReviewTextAlign) => void; onDelete: () => void }) {
  const editor = useEditor({
    extensions: [StarterKit.configure({ link: { openOnClick: false } })],
    content: block.content,
    editable: !disabled,
    onUpdate: ({ editor: activeEditor }) => onChange(activeEditor.getHTML()),
  });
  useEffect(() => { editor?.setEditable(!disabled); }, [disabled, editor]);
  useEffect(() => { if (editor && editor.getHTML() !== block.content) editor.commands.setContent(block.content); }, [block.content, editor]);
  return <article className="review-block">
    <header><span className="review-drag-handle" title="Drag block"><GripVertical size={18} /></span><input className="review-block-title" aria-label={`Title for ${block.block_id} block`} value={block.title} maxLength={200} required disabled={disabled} onChange={(event) => onTitleChange(event.target.value)} /><span>{block.w}/12</span><button className="icon-button danger" title="Delete block" disabled={disabled} onClick={onDelete}><Trash2 size={15} /></button></header>
    <div className="rich-toolbar" aria-label="Text formatting">
      <button className="icon-button" title="Bold" disabled={disabled} onClick={() => editor?.chain().focus().toggleBold().run()}><Bold size={15} /></button>
      <button className="icon-button" title="Italic" disabled={disabled} onClick={() => editor?.chain().focus().toggleItalic().run()}><Italic size={15} /></button>
      <button className="icon-button" title="Bullet list" disabled={disabled} onClick={() => editor?.chain().focus().toggleBulletList().run()}><List size={15} /></button>
      <button className="icon-button" title="Add link" disabled={disabled} onClick={() => { const href = window.prompt("Link URL"); if (href) editor?.chain().focus().setLink({ href }).run(); }}><Link2 size={15} /></button>
      <span className="toolbar-separator" aria-hidden="true" />
      {TEXT_ALIGNMENTS.map(({ value, label, icon: Icon }) => <button key={value} className="icon-button" title={label} aria-pressed={block.text_align === value} disabled={disabled} onClick={() => onAlignmentChange(value)}><Icon size={15} /></button>)}
    </div>
    <EditorContent editor={editor} className={`review-rich-text text-align-${block.text_align}`} />
  </article>;
}

export function ReviewCanvas({ initialBlocks, disabled, onChange }: { initialBlocks: ReviewBlock[]; disabled: boolean; onChange: (blocks: ReviewBlock[]) => void }) {
  const [blocks, setBlocks] = useState(initialBlocks);
  useEffect(() => setBlocks(initialBlocks), [initialBlocks]);
  const update = (next: ReviewBlock[]) => { setBlocks(next); onChange(next); };
  const layout: Layout[] = blocks.map((block) => ({ i: block.block_id, x: block.x, y: block.y, w: block.w, h: block.h, minW: 3, minH: 3, maxW: 12 }));
  const layoutChange = (nextLayout: Layout[]) => update(blocks.map((block) => { const item = nextLayout.find((value) => value.i === block.block_id); return item ? { ...block, x: item.x, y: item.y, w: item.w, h: item.h } : block; }));
  const addBlock = () => {
    const y = Math.max(0, ...blocks.map((block) => block.y + block.h));
    update([...blocks, { block_id: crypto.randomUUID(), type: "rich_text", title: "New content", content: "<p>Start writing...</p>", x: 0, y, w: 6, h: 4, text_align: "left" }]);
  };
  return <div className="review-builder">
    <div className="review-builder-tools"><span>12-column canvas · drag from the handle · resize from the lower corner</span><button disabled={disabled} onClick={addBlock}><Plus size={16} /> Add text block</button></div>
    <TwelveColumnGrid className="review-grid" layout={layout} cols={12} rowHeight={34} margin={[16, 16]} containerPadding={[0, 0]} compactType="vertical" preventCollision={false} isDraggable={!disabled} isResizable={!disabled} draggableHandle=".review-drag-handle" onLayoutChange={layoutChange}>
      {blocks.map((block) => <div key={block.block_id}><RichTextBlock block={block} disabled={disabled} onChange={(content) => update(blocks.map((item) => item.block_id === block.block_id ? { ...item, content } : item))} onTitleChange={(title) => update(blocks.map((item) => item.block_id === block.block_id ? { ...item, title } : item))} onAlignmentChange={(text_align) => update(blocks.map((item) => item.block_id === block.block_id ? { ...item, text_align } : item))} onDelete={() => update(blocks.filter((item) => item.block_id !== block.block_id))} /></div>)}
    </TwelveColumnGrid>
  </div>;
}
