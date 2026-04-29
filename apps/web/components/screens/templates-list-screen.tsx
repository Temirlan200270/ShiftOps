"use client";

import { ArrowLeft, FilePlus2, FileStack, Pencil } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { listTemplates, type TemplateListItem } from "@/lib/api/templates";
import { localiseApiFailure } from "@/lib/i18n/api-errors";
import { toast } from "@/lib/stores/toast-store";

interface TemplatesListScreenProps {
  onBack: () => void;
  onOpen: (id: string | null) => void;
}

/**
 * S7 — admin landing page that lists every template in the org and lets
 * admins jump into the editor. Templates with zero tasks still show with
 * a "0 tasks" badge so admins notice the unfinished state.
 *
 * No search/filter for v1: orgs typically own <20 templates. We can revisit
 * after pilot data shows otherwise.
 */
export function TemplatesListScreen({ onBack, onOpen }: TemplatesListScreenProps): React.JSX.Element {
  const tTpl = useTranslations("templates");
  const tErr = useTranslations("errors");
  const [items, setItems] = React.useState<TemplateListItem[] | null>(null);
  const [loading, setLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    const result = await listTemplates();
    if (result.ok) {
      setItems(result.data);
    } else {
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(result, tErr),
      });
    }
    setLoading(false);
  }, [tErr]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{tTpl("listTitle")}</h1>
          <p className="text-xs text-muted-foreground">
            {tTpl("listSubtitle", { count: items?.length ?? 0 })}
          </p>
        </div>
      </header>

      <Button size="block" onClick={() => onOpen(null)} className="mb-4">
        <FilePlus2 className="size-4" />
        {tTpl("createCta")}
      </Button>

      {loading ? (
        <Card className="animate-pulse">
          <CardContent className="p-6 h-32" />
        </Card>
      ) : (items?.length ?? 0) === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileStack className="size-5 text-muted-foreground" />
              {tTpl("emptyTitle")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{tTpl("emptyHint")}</p>
          </CardContent>
        </Card>
      ) : (
        <ul className="space-y-2">
          {items!.map((tpl) => (
            <li key={tpl.id}>
              <Card>
                <button
                  type="button"
                  onClick={() => onOpen(tpl.id)}
                  className="w-full text-left"
                  aria-label={tTpl("editAria", { name: tpl.name })}
                >
                  <CardContent className="p-4 flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{tpl.name}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {tTpl(`role.${tpl.roleTarget}`)} ·{" "}
                        {tTpl("taskCount", { count: tpl.taskCount })}
                      </p>
                    </div>
                    <Pencil className="size-4 text-muted-foreground shrink-0" />
                  </CardContent>
                </button>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
