"use client";

/**
 * Segmented control whose white thumb slides between options (250ms,
 * ease-standard) instead of jumping (MOTION.md §4.6).
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  kind = "radio",
  label,
}: {
  options: ReadonlyArray<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
  kind?: "radio" | "tab";
  label: string;
}) {
  const index = Math.max(0, options.findIndex((option) => option.value === value));
  return (
    <div
      className="segmented"
      role={kind === "radio" ? "radiogroup" : "tablist"}
      aria-label={label}
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      <span
        className="seg-thumb"
        aria-hidden="true"
        style={{ width: `calc((100% - 6px) / ${options.length})`, transform: `translate3d(${index * 100}%, 0, 0)` }}
      />
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            type="button"
            key={option.value}
            role={kind}
            aria-checked={kind === "radio" ? selected : undefined}
            aria-selected={kind === "tab" ? selected : undefined}
            className={selected ? "is-selected" : undefined}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
