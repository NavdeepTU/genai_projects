"use client";

import { useEffect, useRef, useState } from "react";
import { FileText, MessageCircle, Send } from "lucide-react";

import { postQuery, type QuerySource } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Turn = {
  key: string;
  question: string;
  state: "loading" | { answer: string; sources: QuerySource[]; confidence: number | null } | { error: string };
};

function confidenceLabel(confidence: number | null): { text: string; className: string } | null {
  if (confidence === null) return null;
  if (confidence >= 0.7) {
    return { text: "High confidence", className: "border-primary/30 bg-primary/10 text-primary" };
  }
  if (confidence >= 0.4) {
    return {
      text: "Moderate confidence",
      className: "border-amber-600/30 bg-amber-500/10 text-amber-600 dark:text-amber-400",
    };
  }
  return {
    text: "Low confidence",
    className: "border-destructive/30 bg-destructive/10 text-destructive",
  };
}

function SourceCard({ source }: { source: QuerySource }) {
  return (
    <Card className="gap-1.5 px-3 py-2.5">
      <div className="flex items-center gap-1.5">
        <FileText className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="truncate text-xs font-medium">{source.filename}</span>
      </div>
      <p className="line-clamp-3 text-xs text-muted-foreground">{source.chunk_text}</p>
    </Card>
  );
}

function AnswerBubble({ turn }: { turn: Turn }) {
  if (turn.state === "loading") {
    return (
      <div className="flex flex-col gap-2">
        <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
      </div>
    );
  }

  if ("error" in turn.state) {
    return <p className="text-sm text-destructive">{turn.state.error}</p>;
  }

  const { answer, sources, confidence } = turn.state;
  const label = confidenceLabel(confidence);

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm whitespace-pre-wrap">{answer}</p>
      {label && (
        <Badge variant="outline" className={cn("w-fit", label.className)}>
          {label.text}
        </Badge>
      )}
      {sources.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-muted-foreground">Sources</span>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {sources.map((source, i) => (
              <SourceCard key={`${source.document_id}-${i}`} source={source} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-2 py-24 text-center">
      <MessageCircle className="size-8 text-muted-foreground" strokeWidth={1.5} />
      <p className="text-lg font-medium">Ask a question</p>
      <p className="text-sm text-muted-foreground">
        Ask anything about the documents you have access to — answers are grounded only in
        what&apos;s actually there.
      </p>
    </div>
  );
}

export default function QueryPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isSubmitting) return;

    const key = `${Date.now()}-${Math.random()}`;
    setTurns((current) => [...current, { key, question: trimmed, state: "loading" }]);
    setQuestion("");
    setIsSubmitting(true);

    try {
      const result = await postQuery(trimmed);
      setTurns((current) =>
        current.map((t) =>
          t.key === key
            ? { ...t, state: { answer: result.answer, sources: result.sources, confidence: result.confidence } }
            : t,
        ),
      );
    } catch (err) {
      setTurns((current) =>
        current.map((t) =>
          t.key === key
            ? { ...t, state: { error: err instanceof Error ? err.message : "Something went wrong" } }
            : t,
        ),
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-3xl flex-col px-4">
      <div className="flex-1 overflow-y-auto py-6">
        {turns.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="flex flex-col gap-6">
            {turns.map((turn) => (
              <div key={turn.key} className="flex flex-col gap-3">
                <div className="ml-auto max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">
                  {turn.question}
                </div>
                <div className="max-w-[85%]">
                  <AnswerBubble turn={turn} />
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex items-center gap-2 border-t border-border py-4">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about your documents..."
          disabled={isSubmitting}
          className="h-9 flex-1 rounded-md border border-border bg-transparent px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50"
        />
        <Button type="submit" disabled={isSubmitting || !question.trim()} size="icon">
          <Send />
        </Button>
      </form>
    </div>
  );
}
