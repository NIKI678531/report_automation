import {
  useRef,
  useState,
  type InputHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { useLocale } from "../i18n";

export type MarkerPlacement = "before" | "after";

const SUPERSCRIPT_DIGITS: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
  "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
};
const VALID_MARKER = /^[0-9⁰¹²³⁴⁵⁶⁷⁸⁹*†‡]{1,8}$/u;

export function normalizeSuperscriptMarker(value: string): string | null {
  const trimmed = value.trim();
  if (!VALID_MARKER.test(trimmed)) return null;
  return [...trimmed].map((character) => SUPERSCRIPT_DIGITS[character] ?? character).join("");
}

export function insertMarkerAtSelection(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  marker: string,
  placement: MarkerPlacement,
): { value: string; selectionStart: number; selectionEnd: number } {
  const at = placement === "before" ? selectionStart : selectionEnd;
  const nextValue = `${value.slice(0, at)}${marker}${value.slice(at)}`;
  if (selectionStart === selectionEnd) {
    const cursor = at + marker.length;
    return { value: nextValue, selectionStart: cursor, selectionEnd: cursor };
  }
  return {
    value: nextValue,
    selectionStart: placement === "before" ? selectionStart + marker.length : selectionStart,
    selectionEnd: placement === "before" ? selectionEnd + marker.length : selectionEnd,
  };
}

function useMarkerSelection<T extends HTMLInputElement | HTMLTextAreaElement>(
  value: string,
  onValueChange: (value: string) => void,
) {
  const field = useRef<T>(null);
  const selection = useRef({ start: 0, end: 0 });
  const rememberSelection = () => {
    const node = field.current;
    if (node) selection.current = { start: node.selectionStart ?? 0, end: node.selectionEnd ?? 0 };
  };
  const insert = (marker: string, placement: MarkerPlacement) => {
    const next = insertMarkerAtSelection(
      value, selection.current.start, selection.current.end, marker, placement,
    );
    onValueChange(next.value);
    window.requestAnimationFrame(() => {
      field.current?.focus();
      field.current?.setSelectionRange(next.selectionStart, next.selectionEnd);
      selection.current = { start: next.selectionStart, end: next.selectionEnd };
    });
  };
  return { field, insert, rememberSelection, selection };
}

export function SuperscriptMarkerControl({
  disabled,
  onInsert,
}: {
  disabled: boolean;
  onInsert: (marker: string, placement: MarkerPlacement) => void;
}) {
  const { t } = useLocale();
  const [draft, setDraft] = useState("1");
  const marker = normalizeSuperscriptMarker(draft);
  return <div className="superscript-marker-control" role="group" aria-label={t("footnoteMarker")}>
    <label>
      <span>{t("markerValue")}</span>
      <input
        aria-label={t("markerValue")}
        value={draft}
        maxLength={8}
        disabled={disabled}
        aria-invalid={!marker}
        onChange={(event) => setDraft(event.target.value)}
      />
    </label>
    <button
      type="button"
      disabled={disabled || !marker}
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => marker && onInsert(marker, "before")}
    >{t("insertMarkerBefore")}</button>
    <button
      type="button"
      disabled={disabled || !marker}
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => marker && onInsert(marker, "after")}
    >{t("insertMarkerAfter")}</button>
    {!marker && <small role="alert">{t("invalidMarker")}</small>}
  </div>;
}

export function MarkerTextarea({
  value,
  disabled = false,
  onValueChange,
  ...props
}: Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "disabled" | "onChange"> & {
  value: string;
  disabled?: boolean;
  onValueChange: (value: string) => void;
}) {
  const { field, insert, rememberSelection, selection } = useMarkerSelection<HTMLTextAreaElement>(value, onValueChange);
  return <div className="marker-textarea">
    <textarea
      {...props}
      ref={field}
      value={value}
      disabled={disabled}
      onSelect={rememberSelection}
      onBlur={rememberSelection}
      onChange={(event) => {
        selection.current = {
          start: event.currentTarget.selectionStart,
          end: event.currentTarget.selectionEnd,
        };
        onValueChange(event.currentTarget.value);
      }}
    />
    <SuperscriptMarkerControl disabled={disabled} onInsert={insert} />
  </div>;
}

export function MarkerInput({
  value,
  disabled = false,
  onValueChange,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "disabled" | "onChange"> & {
  value: string;
  disabled?: boolean;
  onValueChange: (value: string) => void;
}) {
  const { field, insert, rememberSelection, selection } = useMarkerSelection<HTMLInputElement>(value, onValueChange);
  return <div className="marker-input">
    <input
      {...props}
      ref={field}
      value={value}
      disabled={disabled}
      onSelect={rememberSelection}
      onBlur={rememberSelection}
      onChange={(event) => {
        selection.current = {
          start: event.currentTarget.selectionStart ?? 0,
          end: event.currentTarget.selectionEnd ?? 0,
        };
        onValueChange(event.currentTarget.value);
      }}
    />
    <SuperscriptMarkerControl disabled={disabled} onInsert={insert} />
  </div>;
}
