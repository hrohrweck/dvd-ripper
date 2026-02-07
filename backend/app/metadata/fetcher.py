"""Metadata fetching from TMDB and OMDB."""
from typing import Dict, Optional, List
import httpx
import asyncio
from app.config import Settings, get_settings


class MetadataProvider:
    """Base class for metadata providers."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        
    async def search(self, title: str, year: Optional[int] = None) -> List[Dict]:
        """Search for a title."""
        raise NotImplementedError
        
    async def get_details(self, id: str) -> Optional[Dict]:
        """Get detailed information."""
        raise NotImplementedError


class TMDBProvider(MetadataProvider):
    """The Movie Database provider."""
    
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def search(self, title: str, year: Optional[int] = None) -> List[Dict]:
        """Search for movies by title."""
        if not self.api_key:
            return []
            
        params = {
            "api_key": self.api_key,
            "query": title,
            "language": "en-US",
            "page": 1
        }
        
        if year:
            params["year"] = year
            
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/search/movie",
                params=params
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            for movie in data.get("results", [])[:5]:  # Top 5 results
                results.append({
                    "id": str(movie.get("id")),
                    "title": movie.get("title"),
                    "original_title": movie.get("original_title"),
                    "year": movie.get("release_date", ":").split("-")[0] if movie.get("release_date") else None,
                    "plot": movie.get("overview"),
                    "poster_url": self._get_image_url(movie.get("poster_path")),
                    "backdrop_url": self._get_image_url(movie.get("backdrop_path"), "w1280"),
                    "popularity": movie.get("popularity"),
                    "vote_average": movie.get("vote_average"),
                    "provider": "tmdb"
                })
            return results
            
        except Exception as e:
            print(f"TMDB search error: {e}")
            return []
            
    async def get_details(self, movie_id: str) -> Optional[Dict]:
        """Get detailed movie information."""
        if not self.api_key:
            return None
            
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/movie/{movie_id}",
                params={
                    "api_key": self.api_key,
                    "append_to_response": "credits",
                    "language": "en-US"
                }
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract cast
            cast = []
            for actor in data.get("credits", {}).get("cast", [])[:5]:
                cast.append(actor.get("name"))
                
            # Extract director
            director = None
            for crew in data.get("credits", {}).get("crew", []):
                if crew.get("job") == "Director":
                    director = crew.get("name")
                    break
                    
            # Extract genres
            genres = [g.get("name") for g in data.get("genres", [])]
            
            return {
                "id": str(data.get("id")),
                "imdb_id": data.get("imdb_id"),
                "title": data.get("title"),
                "original_title": data.get("original_title"),
                "year": data.get("release_date", ":").split("-")[0] if data.get("release_date") else None,
                "plot": data.get("overview"),
                "poster_url": self._get_image_url(data.get("poster_path")),
                "backdrop_url": self._get_image_url(data.get("backdrop_path"), "w1280"),
                "runtime": data.get("runtime"),
                "tagline": data.get("tagline"),
                "director": director,
                "cast": cast,
                "genres": genres,
                "popularity": data.get("popularity"),
                "vote_average": data.get("vote_average"),
                "provider": "tmdb"
            }
            
        except Exception as e:
            print(f"TMDB details error: {e}")
            return None
            
    def _get_image_url(self, path: Optional[str], size: str = "w500") -> Optional[str]:
        """Construct full image URL."""
        if path:
            return f"{self.IMAGE_BASE_URL}/{size}{path}"
        return None


class OMDBProvider(MetadataProvider):
    """OMDb API provider."""
    
    BASE_URL = "http://www.omdbapi.com"
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def search(self, title: str, year: Optional[int] = None) -> List[Dict]:
        """Search for movies by title."""
        if not self.api_key:
            return []
            
        params = {
            "apikey": self.api_key,
            "s": title,
            "type": "movie",
            "r": "json"
        }
        
        if year:
            params["y"] = year
            
        try:
            response = await self.client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("Response") != "True":
                return []
                
            results = []
            for movie in data.get("Search", [])[:5]:
                results.append({
                    "id": movie.get("imdbID"),
                    "title": movie.get("Title"),
                    "year": movie.get("Year"),
                    "poster_url": movie.get("Poster") if movie.get("Poster") != "N/A" else None,
                    "provider": "omdb"
                })
            return results
            
        except Exception as e:
            print(f"OMDB search error: {e}")
            return []
            
    async def get_details(self, imdb_id: str) -> Optional[Dict]:
        """Get detailed movie information."""
        if not self.api_key:
            return None
            
        try:
            response = await self.client.get(
                self.BASE_URL,
                params={
                    "apikey": self.api_key,
                    "i": imdb_id,
                    "plot": "full",
                    "r": "json"
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("Response") != "True":
                return None
                
            # Parse runtime
            runtime = None
            runtime_str = data.get("Runtime", "")
            if "min" in runtime_str:
                try:
                    runtime = int(runtime_str.split()[0])
                except:
                    pass
                    
            # Parse year
            year = None
            try:
                year = int(data.get("Year", "").split("–")[0])
            except:
                pass
                
            return {
                "id": data.get("imdbID"),
                "imdb_id": data.get("imdbID"),
                "title": data.get("Title"),
                "year": year,
                "plot": data.get("Plot") if data.get("Plot") != "N/A" else None,
                "poster_url": data.get("Poster") if data.get("Poster") != "N/A" else None,
                "runtime": runtime,
                "director": data.get("Director") if data.get("Director") != "N/A" else None,
                "cast": [a.strip() for a in data.get("Actors", "").split(",")] if data.get("Actors") != "N/A" else [],
                "genres": [g.strip() for g in data.get("Genre", "").split(",")] if data.get("Genre") != "N/A" else [],
                "rated": data.get("Rated"),
                "rating": data.get("imdbRating") if data.get("imdbRating") != "N/A" else None,
                "provider": "omdb"
            }
            
        except Exception as e:
            print(f"OMDB details error: {e}")
            return None


class MetadataFetcher:
    """Unified metadata fetcher using multiple providers."""
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.providers: List[MetadataProvider] = []
        
        # Initialize providers
        api_keys = self.settings.metadata.api_keys
        
        if "tmdb" in self.settings.metadata.providers:
            tmdb_key = api_keys.get("tmdb") or self.settings.tmdb_api_key
            if tmdb_key:
                self.providers.append(TMDBProvider(tmdb_key))
                
        if "omdb" in self.settings.metadata.providers:
            omdb_key = api_keys.get("omdb") or self.settings.omdb_api_key
            if omdb_key:
                self.providers.append(OMDBProvider(omdb_key))
                
    async def search(self, title: str, year: Optional[int] = None) -> List[Dict]:
        """Search all providers and merge results."""
        if not self.providers:
            return []
            
        # Search all providers concurrently
        tasks = [provider.search(title, year) for provider in self.providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_results = []
        for provider_results in results:
            if isinstance(provider_results, list):
                all_results.extend(provider_results)
                
        # Sort by popularity/rating if available
        all_results.sort(
            key=lambda x: (x.get("popularity", 0) or 0) + (x.get("vote_average", 0) or 0),
            reverse=True
        )
        
        return all_results[:10]  # Return top 10
        
    async def get_details(self, provider: str, item_id: str) -> Optional[Dict]:
        """Get details from specific provider."""
        for p in self.providers:
            if isinstance(p, TMDBProvider) and provider == "tmdb":
                return await p.get_details(item_id)
            elif isinstance(p, OMDBProvider) and provider == "omdb":
                return await p.get_details(item_id)
        return None
