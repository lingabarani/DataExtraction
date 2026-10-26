"use client";
import { useMemo } from "react";
import Link from "next/link";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Phone, ChevronRight, MapPin } from "lucide-react";
import type { Lead } from "@/hooks/use-leads";

const DEFAULT_CENTER: [number, number] = [37.0902, -95.7129]; // US geographic center
const DEFAULT_ZOOM = 4;

type PriorityType = "HIGH" | "MEDIUM" | "LOW";

const PRIORITY_COLOR: Record<PriorityType, string> = {
  HIGH: "#10b981",
  MEDIUM: "#f59e0b",
  LOW: "#6b7280",
};

function getLeadPriority(lead: Lead): PriorityType {
  const score = lead.lead_score ?? 0;
  if (score >= 80) return "HIGH";
  if (score >= 50) return "MEDIUM";
  return "LOW";
}

function markerIcon(priority: PriorityType) {
  const color = PRIORITY_COLOR[priority];
  return L.divIcon({
    className: "oe-marker",
    html: `
      <div class="oe-marker-pin" style="--pin-color:${color}">
        <svg width="30" height="38" viewBox="0 0 30 38" xmlns="http://www.w3.org/2000/svg">
          <path d="M15 0C6.7 0 0 6.7 0 15c0 10.5 15 23 15 23s15-12.5 15-23C30 6.7 23.3 0 15 0z" fill="var(--pin-color)"/>
          <circle cx="15" cy="15" r="6" fill="white"/>
        </svg>
      </div>
    `,
    iconSize: [30, 38],
    iconAnchor: [15, 38],
    popupAnchor: [0, -34],
  });
}

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  useMemo(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 12);
      return;
    }
    map.fitBounds(L.latLngBounds(points), { padding: [40, 40] });
  }, [points, map]);
  return null;
}

interface Props {
  leads: Lead[];
}

interface GeocodedLead extends Lead {
  lat: number;
  lng: number;
}

export function LeadsMap({ leads }: Props) {
  const pinned = useMemo<GeocodedLead[]>(() => {
    return leads
      .map((l) => {
        const lat = (l as any).lat ?? l.company?.latitude;
        const lng = (l as any).lng ?? l.company?.longitude;
        if (typeof lat === "number" && typeof lng === "number" && !isNaN(lat) && !isNaN(lng)) {
          return { ...l, lat, lng };
        }
        return null;
      })
      .filter((l): l is GeocodedLead => l !== null);
  }, [leads]);

  const points = useMemo<[number, number][]>(
    () => pinned.map((l) => [l.lat, l.lng]),
    [pinned],
  );

  if (leads.length > 0 && pinned.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
        <MapPin className="w-8 h-8 text-muted-foreground/40 mb-1" />
        <p className="text-sm font-medium">No geographical coordinates available for these leads</p>
        <p className="text-xs text-muted-foreground">
          Coordinates are enriched automatically through company geocoding
        </p>
      </div>
    );
  }

  return (
    <div className="h-[520px] w-full overflow-hidden rounded-b-lg">
      <style>{`
        .oe-marker-pin { filter: drop-shadow(0 2px 4px rgb(0 0 0 / 0.35)); transition: transform 0.15s ease; }
        .oe-marker-pin:hover { transform: scale(1.15) translateY(-2px); }
        .leaflet-popup-content-wrapper { border-radius: 0.75rem; }
      `}</style>
      <MapContainer
        center={pinned[0] ? [pinned[0].lat, pinned[0].lng] : DEFAULT_CENTER}
        zoom={pinned.length ? undefined : DEFAULT_ZOOM}
        scrollWheelZoom
        className="h-full w-full"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds points={points} />
        {pinned.map((lead) => {
          const priority = getLeadPriority(lead);
          const displayName = lead.full_name || lead.company_name || "Lead";
          const address = [lead.city, lead.state_code || lead.state, lead.country].filter(Boolean).join(", ");
          return (
            <Marker key={lead.id} position={[lead.lat, lead.lng]} icon={markerIcon(priority)}>
              <Popup>
                <div className="min-w-[180px] space-y-1">
                  <p className="text-sm font-semibold leading-tight">{displayName}</p>
                  {address && <p className="text-xs text-muted-foreground">{address}</p>}
                  {lead.phone && (
                    <div className="flex items-center gap-1 pt-1 text-xs text-muted-foreground">
                      <Phone className="w-3 h-3" />{lead.phone}
                    </div>
                  )}
                  {lead.lead_score != null && (
                    <div className="flex items-center gap-1 text-xs font-mono font-medium text-primary">
                      Score: {lead.lead_score}
                    </div>
                  )}
                  <Link
                    href={`/leads/${lead.id}`}
                    className="flex items-center gap-0.5 pt-1 text-xs font-medium text-primary hover:underline"
                  >
                    View details<ChevronRight className="w-3 h-3" />
                  </Link>
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>
    </div>
  );
}
