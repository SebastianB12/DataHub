"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { COUNTRIES, type IndicatorCategory } from "@/lib/indicators";

interface SearchItem {
  label: string;
  hint: string;
  href: string;
  haystack: string;
}

function buildItems(catalog: IndicatorCategory[]): SearchItem[] {
  const items: SearchItem[] = [];

  for (const cat of catalog) {
    for (const ind of cat.indicators) {
      for (const country of COUNTRIES) {
        items.push({
          label: `${ind.name_de} — ${country.name_de}`,
          hint: `${country.flag} ${cat.name_de}`,
          href: `/indicators/${ind.slug}/${country.code.toLowerCase()}`,
          haystack: `${ind.name_de} ${ind.name} ${ind.slug} ${country.name_de} ${country.name} ${country.code}`.toLowerCase(),
        });
      }
    }
  }

  for (const cat of catalog) {
    for (const ind of cat.indicators) {
      items.push({
        label: `${ind.name_de} — Ländervergleich`,
        hint: cat.name_de,
        href: `/indicators/${ind.slug}`,
        haystack: `${ind.name_de} ${ind.name} ${ind.slug} vergleich`.toLowerCase(),
      });
    }
  }

  for (const country of COUNTRIES) {
    items.push({
      label: `${country.flag} ${country.name_de} — Länderprofil`,
      hint: country.name,
      href: `/countries/${country.code.toLowerCase()}`,
      haystack: `${country.name_de} ${country.name} ${country.code} profil`.toLowerCase(),
    });
  }

  return items;
}

function filterItems(items: SearchItem[], query: string): SearchItem[] {
  if (!query.trim()) return [];
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
  const scored: { item: SearchItem; score: number }[] = [];
  for (const item of items) {
    if (tokens.every((t) => item.haystack.includes(t))) {
      // Prefer shorter haystacks (more specific matches rank higher)
      scored.push({ item, score: item.haystack.length });
    }
  }
  scored.sort((a, b) => a.score - b.score);
  return scored.slice(0, 12).map((s) => s.item);
}

export function SearchPalette({ catalog }: { catalog: IndicatorCategory[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const items = useMemo(() => buildItems(catalog), [catalog]);
  const results = useMemo(() => filterItems(items, query), [items, query]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIdx(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    setActiveIdx(0);
  }, [query]);

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && results[activeIdx]) {
      e.preventDefault();
      setOpen(false);
      router.push(results[activeIdx].href);
    }
  }

  const overlay = open ? (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-black/60 p-4 pt-[12vh]"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-lg rounded-lg border border-border bg-popover shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Indikator, Land oder Kombination..."
            className="flex-1 bg-transparent outline-none text-sm"
          />
          <kbd className="rounded border border-border px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">ESC</kbd>
        </div>

        {results.length > 0 ? (
          <ul className="max-h-[60vh] overflow-y-auto py-1">
            {results.map((item, i) => (
              <li key={item.href}>
                <button
                  type="button"
                  onMouseEnter={() => setActiveIdx(i)}
                  onClick={() => {
                    setOpen(false);
                    router.push(item.href);
                  }}
                  className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm transition-colors ${
                    i === activeIdx ? "bg-accent text-accent-foreground" : "hover:bg-muted/50"
                  }`}
                >
                  <span>{item.label}</span>
                  <span className="text-xs text-muted-foreground">{item.hint}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            {query.trim() ? "Nichts gefunden" : "Tippe einen Suchbegriff..."}
          </div>
        )}
      </div>
    </div>
  ) : null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted transition-colors w-full max-w-sm"
        aria-label="Suchen"
      >
        <Search className="h-4 w-4" />
        <span className="flex-1 text-left">Suchen...</span>
        <kbd className="hidden sm:inline-block rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-mono">
          ⌘K
        </kbd>
      </button>

      {typeof document !== "undefined" && overlay
        ? createPortal(overlay, document.body)
        : null}
    </>
  );
}
