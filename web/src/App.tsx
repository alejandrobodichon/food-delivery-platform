import { OfflineBanner } from "./OfflineBanner";
import { RestaurantList } from "./RestaurantList";

function App() {
  return (
    <main>
      <OfflineBanner />
      <h1>Restaurants</h1>
      <RestaurantList />
    </main>
  );
}

export default App;