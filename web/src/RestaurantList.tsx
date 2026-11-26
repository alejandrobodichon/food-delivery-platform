import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchJson } from "./api/client";
import type { components } from "./api/schema";

type Restaurant = components["schemas"]["RestaurantResponse"];

export function RestaurantList() {
  const { data, isPending, error } = useQuery({
    queryKey: ["restaurants"],
    queryFn: ({ signal }) => fetchJson<Restaurant[]>("/v1/restaurants", signal),
  });
  const [onlyOpen, setOnlyOpen] = useState(false);

  if (isPending) return <p>Loading…</p>;
  if (error) return <p>Could not load restaurants: {error.message}</p>;
  if (data.length === 0) return <p>No restaurants yet.</p>;

  const visible = onlyOpen ? data.filter((r) => r.is_open) : data;

  return (
    <div>
      <label>
        <input
          type="checkbox"
          checked={onlyOpen}
          onChange={(event) => setOnlyOpen(event.target.checked)}
        />
        Only open restaurants
      </label>
      <ul>
        {visible.map((restaurant) => (
          <li key={restaurant.id}>
            {restaurant.name} {restaurant.is_open ? "🟢" : "🔴 closed"}
          </li>
        ))}
      </ul>
    </div>
  );
}
