import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function StatTile({
  icon: Icon,
  label,
  value,
  placeholder,
  className,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value?: string | number;
  placeholder?: string;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Icon className="size-4 text-muted-foreground" />
          <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        {placeholder ? (
          <p className="text-xs text-muted-foreground">{placeholder}</p>
        ) : (
          <p className="text-3xl font-semibold">{value}</p>
        )}
      </CardContent>
    </Card>
  );
}
