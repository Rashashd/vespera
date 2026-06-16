import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, X, Save } from "lucide-react";
import { useSetSeverityKeywords } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

/**
 * Edits a client's custom severity-escalation keywords (spec 8 FR-004). Any finding text
 * matching one of these keywords is escalated regardless of the model's severity score.
 */
export function SeverityKeywordsEditor({
  clientId,
  keywords,
}: {
  clientId: number | null;
  keywords: string[];
}) {
  const save = useSetSeverityKeywords(clientId);
  const [list, setList] = useState<string[]>(keywords);
  const [draft, setDraft] = useState("");

  // Re-sync when the acting client changes.
  useEffect(() => {
    setList(keywords);
  }, [keywords]);

  const dirty =
    list.length !== keywords.length ||
    list.some((k, i) => k !== keywords[i]);

  const add = () => {
    const kw = draft.trim();
    if (!kw) return;
    if (list.some((k) => k.toLowerCase() === kw.toLowerCase())) {
      setDraft("");
      return;
    }
    setList((prev) => [...prev, kw]);
    setDraft("");
  };

  const remove = (kw: string) =>
    setList((prev) => prev.filter((k) => k !== kw));

  const persist = () => {
    save.mutate(list, {
      onSuccess: () => toast.success("Severity keywords saved."),
      onError: () => toast.error("Failed to save keywords."),
    });
  };

  return (
    <section className="rounded border bg-card p-4 space-y-3">
      <div>
        <h2 className="text-sm font-semibold">Severity escalation keywords</h2>
        <p className="text-xs text-muted-foreground">
          Findings whose text contains any of these are escalated as serious,
          regardless of the model score.
        </p>
      </div>

      <div className="flex flex-wrap gap-1">
        {list.length === 0 && (
          <span className="text-xs text-muted-foreground">
            No custom keywords. Default severity rules apply.
          </span>
        )}
        {list.map((kw) => (
          <Badge key={kw} variant="secondary" className="text-xs flex items-center gap-1">
            {kw}
            <button
              type="button"
              onClick={() => remove(kw)}
              className="ml-0.5 hover:text-destructive"
              aria-label={`Remove ${kw}`}
            >
              <X className="h-3 w-3" />
            </button>
          </Badge>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="e.g. anaphylaxis"
          className="max-w-xs"
        />
        <Button variant="outline" size="sm" onClick={add} disabled={!draft.trim()}>
          <Plus className="h-3 w-3 mr-1" />
          Add
        </Button>
        {dirty && (
          <Button size="sm" onClick={persist} disabled={save.isPending}>
            <Save className="h-3 w-3 mr-1" />
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        )}
      </div>
    </section>
  );
}
