import { useEffect } from "react";
import L from "leaflet";
import {
  Circle,
  CircleMarker,
  MapContainer,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";

type Ring = {
  label: string;
  km: number;
  color: string;
};

function Fit({ center, maxKm }: { center: [number, number]; maxKm: number }) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;

    const lat = Number(center[0]);
    const lng = Number(center[1]);
    const km = Number(maxKm);

    // Don't try to fit if the backend has not supplied valid coordinates
    if (
      !Number.isFinite(lat) ||
      !Number.isFinite(lng) ||
      !Number.isFinite(km)
    ) {
      return;
    }

    const runFit = () => {
      try {
        const bounds = L.circle([lat, lng], {
          radius: km * 1000,
        }).getBounds();

        map.fitBounds(bounds, {
          padding: [20, 20],
        });
      } catch (error) {
        console.error("Leaflet fitBounds error:", error);
      }
    };

    // Wait until Leaflet has completely initialized
    if (map._loaded) {
      requestAnimationFrame(runFit);
    } else {
      map.whenReady(() => {
        requestAnimationFrame(runFit);
      });
    }
  }, [map, center[0], center[1], maxKm]);

  return null;
}

/**
 * Donor coordinates are private.
 * Each matched donor is represented by a ring showing
 * their distance from the hospital.
 */
export default function MatchMap({
  center,
  maxKm,
  rings,
}: {
  center: [number, number];
  maxKm: number;
  rings: Ring[];
}) {
  const safeCenter: [number, number] = [Number(center[0]), Number(center[1])];

  const safeMaxKm = Number(maxKm);

  // Don't render Leaflet with invalid coordinates
  if (
    !Number.isFinite(safeCenter[0]) ||
    !Number.isFinite(safeCenter[1]) ||
    !Number.isFinite(safeMaxKm)
  ) {
    return (
      <div className="h-80 w-full rounded border border-line flex items-center justify-center">
        <p className="text-sm text-ink/60">
          Hospital location is not available.
        </p>
      </div>
    );
  }

  return (
    <div>
      <MapContainer
        center={safeCenter}
        zoom={11}
        className="h-80 w-full rounded border border-line"
        scrollWheelZoom={false}
      >
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <Fit center={safeCenter} maxKm={safeMaxKm} />

        {/* Hospital maximum matching radius */}
        <Circle
          center={safeCenter}
          radius={safeMaxKm * 1000}
          pathOptions={{
            color: "#16262E",
            weight: 1,
            dashArray: "4 4",
            fillOpacity: 0.03,
          }}
        />

        {/* Donor distance rings */}
        {rings.map((r) => (
          <Circle
            key={r.label}
            center={safeCenter}
            radius={Number(r.km) * 1000}
            pathOptions={{
              color: r.color,
              weight: 3,
              fill: false,
            }}
          >
            <Tooltip sticky>
              {r.label} · {r.km} km
            </Tooltip>
          </Circle>
        ))}

        {/* Hospital */}
        <CircleMarker
          center={safeCenter}
          radius={7}
          pathOptions={{
            color: "#B3202A",
            fillColor: "#B3202A",
            fillOpacity: 1,
          }}
        >
          <Tooltip>Your hospital</Tooltip>
        </CircleMarker>
      </MapContainer>

      <p className="mt-1 text-xs text-ink/60">
        Rings show each donor&apos;s distance. Exact donor locations stay
        private.
      </p>
    </div>
  );
}
