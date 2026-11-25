import { useEffect, useState } from "react";
import type { components } from "./api/schema";

type Restaurant = components["schemas"]["RestaurantResponse"];

export function RestaurantList() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/v1/restaurants")
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<Restaurant[]>;
      })
      .then(setRestaurants)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Unknown error"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading…</p>;
  if (error) return <p>Could not load restaurants: {error}</p>;
  if (restaurants.length === 0) return <p>No restaurants yet.</p>;

  return (
    <ul>
      {restaurants.map((restaurant) => (
        <li key={restaurant.id}>
          {restaurant.name} {restaurant.is_open ? "🟢" : "🔴 closed"}
        </li>
      ))}
    </ul>
  );
}