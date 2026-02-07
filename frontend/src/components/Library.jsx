import React, { useState, useEffect } from 'react'
import { api } from '../App'

function Library() {
  const [movies, setMovies] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedMovie, setSelectedMovie] = useState(null)

  useEffect(() => {
    fetchMovies()
  }, [search])

  const fetchMovies = async () => {
    try {
      const params = search ? { search } : {}
      const response = await api.get('/library', { params })
      setMovies(response.data)
    } catch (err) {
      console.error('Failed to fetch library:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id, deleteFile = false) => {
    if (!confirm('Are you sure you want to delete this entry?')) return
    
    try {
      await api.delete(`/library/${id}`, { params: { delete_file: deleteFile } })
      fetchMovies()
      setSelectedMovie(null)
    } catch (err) {
      alert('Failed to delete')
    }
  }

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  if (loading) return <div className="loading">Loading library...</div>

  return (
    <div>
      <h1>Library</h1>

      <div className="search-box">
        <input
          type="text"
          placeholder="Search movies..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className="btn btn-primary" onClick={fetchMovies}>Search</button>
      </div>

      {movies.length === 0 ? (
        <div className="card empty-state">
          <div className="empty-state-icon">🎬</div>
          <p>No movies in library yet. Start ripping some DVDs!</p>
        </div>
      ) : (
        <div className="movie-grid">
          {movies.map(movie => (
            <div 
              key={movie.id} 
              className="movie-card"
              onClick={() => setSelectedMovie(movie)}
            >
              <div className="movie-poster">
                {movie.poster_url ? (
                  <img src={movie.poster_url} alt={movie.title} />
                ) : (
                  '📀'
                )}
              </div>
              <div className="movie-info">
                <div className="movie-title">{movie.title}</div>
                {movie.year && (
                  <div className="movie-year">{movie.year}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Movie Detail Modal */}
      {selectedMovie && (
        <div className="modal-overlay" onClick={() => setSelectedMovie(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{selectedMovie.title}</h3>
              <button 
                className="btn btn-secondary"
                onClick={() => setSelectedMovie(null)}
              >
                ✕
              </button>
            </div>
            <div className="modal-body">
              <div style={{ display: 'flex', gap: 24 }}>
                <div style={{ width: 200, flexShrink: 0 }}>
                  {selectedMovie.poster_url ? (
                    <img 
                      src={selectedMovie.poster_url} 
                      alt={selectedMovie.title}
                      style={{ width: '100%', borderRadius: 8 }}
                    />
                  ) : (
                    <div className="movie-poster" style={{ height: 300 }}>📀</div>
                  )}
                </div>
                <div style={{ flex: 1 }}>
                  {selectedMovie.plot && (
                    <p style={{ marginBottom: 16 }}>{selectedMovie.plot}</p>
                  )}
                  
                  <div style={{ display: 'grid', gap: 8, color: 'var(--text-muted)' }}>
                    {selectedMovie.year && (
                      <div><strong>Year:</strong> {selectedMovie.year}</div>
                    )}
                    {selectedMovie.genre && (
                      <div><strong>Genre:</strong> {selectedMovie.genre}</div>
                    )}
                    {selectedMovie.runtime && (
                      <div><strong>Runtime:</strong> {selectedMovie.runtime} min</div>
                    )}
                    <div><strong>File Size:</strong> {formatFileSize(selectedMovie.file_size)}</div>
                    <div><strong>Format:</strong> {selectedMovie.file_format}</div>
                    {selectedMovie.file_path && (
                      <div><strong>Location:</strong> {selectedMovie.file_path}</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button 
                className="btn btn-secondary"
                onClick={() => handleDelete(selectedMovie.id, false)}
              >
                Remove Entry
              </button>
              <button 
                className="btn btn-danger"
                onClick={() => handleDelete(selectedMovie.id, true)}
              >
                Delete File & Entry
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Library
