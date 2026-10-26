"use client";

import React, { useState, useEffect, useRef } from "react";
import { MapPin, Phone, Globe, ExternalLink, ShieldAlert, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Lead } from "@/hooks/use-leads";

interface GoogleLeadsMapProps {
  leads: Lead[];
  apiKey?: string;
  className?: string;
}

export function GoogleLeadsMap({ leads, apiKey, className }: GoogleLeadsMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  // Filter leads with valid coordinates (direct or inside company JSONB)
  const validLeads = leads
    .map((l) => {
      const lat = (l as any).lat ?? (l as any).latitude ?? l.company?.latitude;
      const lng = (l as any).lng ?? (l as any).longitude ?? l.company?.longitude;
      if (typeof lat === "number" && typeof lng === "number" && !isNaN(lat) && !isNaN(lng)) {
        return { ...l, lat, lng };
      }
      return null;
    })
    .filter((l): l is Lead & { lat: number; lng: number } => l !== null);

  useEffect(() => {
    if (!apiKey) {
      setApiError("GOOGLE_MAPS_API_KEY not configured. Set GOOGLE_MAPS_API_KEY in .env to enable Google Maps 3D & Advanced Markers.");
      return;
    }

    // Dynamic Google Maps Script injection
    const scriptId = "google-maps-js-sdk";
    if (!document.getElementById(scriptId)) {
      const script = document.createElement("script");
      script.id = scriptId;
      script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=marker&v=weekly`;
      script.async = true;
      script.defer = true;
      script.onload = () => setMapLoaded(true);
      script.onerror = () => setApiError("Failed to load Google Maps SDK.");
      document.head.appendChild(script);
    } else {
      setMapLoaded(true);
    }
  }, [apiKey]);

  return (
    <div className={`relative w-full h-[540px] rounded-xl border border-border overflow-hidden bg-muted/20 ${className || ""}`}>
      {apiError ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center bg-card/90 backdrop-blur-sm z-10 space-y-3">
          <div className="w-12 h-12 rounded-full bg-amber-500/10 flex items-center justify-center text-amber-500">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <div className="space-y-1 max-w-md">
            <h3 className="font-semibold text-sm text-foreground">Google Maps Platform Enrichment</h3>
            <p className="text-xs text-muted-foreground leading-relaxed">{apiError}</p>
          </div>
          <p className="text-[11px] font-mono text-muted-foreground bg-muted px-3 py-1.5 rounded border border-border">
            Total {validLeads.length} spatial coordinates plotted in local memory
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 w-full max-w-xl text-left mt-2">
            {validLeads.slice(0, 4).map((lead) => (
              <div
                key={lead.id}
                onClick={() => setSelectedLead(lead)}
                className="p-2.5 rounded-lg border border-border bg-background/50 hover:bg-muted/50 cursor-pointer text-xs space-y-1 transition-colors"
              >
                <span className="font-semibold truncate block">{lead.company_name}</span>
                <span className="text-muted-foreground block text-[11px] truncate">{lead.city}, {lead.state}</span>
                <Badge variant="outline" className="text-[10px] mt-1">Score: {lead.lead_score ?? "N/A"}</Badge>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div ref={mapRef} className="w-full h-full" />
      )}

      {/* Selected lead detail overlay */}
      {selectedLead && (
        <div className="absolute bottom-4 left-4 right-4 md:right-auto md:w-80 p-4 rounded-xl border border-border bg-card/95 backdrop-blur-md shadow-xl z-20 space-y-2.5">
          <div className="flex items-start justify-between">
            <div>
              <h4 className="font-semibold text-sm text-foreground">{selectedLead.company_name}</h4>
              <p className="text-xs text-muted-foreground">{selectedLead.city}, {selectedLead.state}</p>
            </div>
            <button
              onClick={() => setSelectedLead(null)}
              className="text-muted-foreground hover:text-foreground text-xs"
            >
              ✕
            </button>
          </div>
          <div className="text-xs space-y-1.5 pt-2 border-t border-border">
            {selectedLead.phone && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Phone className="w-3.5 h-3.5" />
                <span>{selectedLead.phone}</span>
              </div>
            )}
            {(selectedLead.company?.website || selectedLead.domain) && (
              <div className="flex items-center gap-2 text-primary">
                <Globe className="w-3.5 h-3.5" />
                <a
                  href={selectedLead.company?.website ?? `https://${selectedLead.domain}`}
                  target="_blank"
                  rel="noreferrer"
                  className="truncate hover:underline"
                >
                  {selectedLead.company?.website ?? selectedLead.domain}
                </a>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
