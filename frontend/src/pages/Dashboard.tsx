import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getAnalytics } from "../api/client";

interface GenreYearRow {
  genre_name: string;
  release_year: number;
  avg_price: number;
  avg_discount: number;
}

interface PlatformRow {
  platform_combo: string;
  avg_price: number;
  min_price: number;
  max_price: number;
}

export default function Dashboard() {
  const [genreYearRows, setGenreYearRows] = useState<GenreYearRow[]>([]);
  const [platformRows, setPlatformRows] = useState<PlatformRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      getAnalytics<GenreYearRow[]>("price-discount-by-genre-year"),
      getAnalytics<PlatformRow[]>("price-variance-by-platform"),
    ])
      .then(([genreYear, platform]) => {
        setGenreYearRows(genreYear);
        setPlatformRows(platform);
      })
      .catch((err) => setError((err as Error).message));
  }, []);

  if (error) return <p style={{ color: "red" }}>{error}</p>;

  return (
    <div>
      <h1>Price trends</h1>

      <h2>Average price &amp; discount by release year</h2>
      <ResponsiveContainer width="100%" height={360}>
        <BarChart data={genreYearRows}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="release_year" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Bar dataKey="avg_price" fill="#4f8dfd" name="Avg price (USD)" />
        </BarChart>
      </ResponsiveContainer>

      <h2>Price variance by platform combination</h2>
      <ResponsiveContainer width="100%" height={360}>
        <BarChart data={platformRows}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="platform_combo" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Bar dataKey="avg_price" fill="#4f8dfd" name="Avg price (USD)" />
          <Bar dataKey="max_price" fill="#f97316" name="Max price (USD)" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
