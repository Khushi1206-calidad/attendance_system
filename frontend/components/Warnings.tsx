import type { ApiWarning } from "@/lib/types";

export function Warnings({ warnings }: { warnings: ApiWarning[] }) {
  return (
    <div className="warnings">
      {warnings.map((warning) => (
        <p key={warning.code} className="warning">
          {warning.message}
        </p>
      ))}
    </div>
  );
}
