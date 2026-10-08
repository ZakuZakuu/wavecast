/** Temporary status-bar experiment; delete once a style is chosen. */
export const LAB_VARIANTS = ["default", "translucent"] as const;
export type LabVariant = (typeof LAB_VARIANTS)[number];

export function isLabVariant(value: string): value is LabVariant {
  return (LAB_VARIANTS as readonly string[]).includes(value);
}

export const STATUS_BAR_STYLE: Record<LabVariant, "default" | "black-translucent"> = {
  default: "default",
  translucent: "black-translucent",
};
