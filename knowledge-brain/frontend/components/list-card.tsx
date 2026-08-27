import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ListCard({
  icon: Icon,
  title,
  isEmpty,
  emptyMessage,
  className,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  isEmpty: boolean;
  emptyMessage: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Icon className="size-4 text-muted-foreground" />
          <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        {isEmpty ? (
          <p className="text-xs text-muted-foreground">{emptyMessage}</p>
        ) : (
          <ul className="flex flex-col gap-3">{children}</ul>
        )}
      </CardContent>
    </Card>
  );
}
