import React, { useState, useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route, Link, Navigate } from 'react-router-dom'
import axios from 'axios'
import './styles.css'

// Components
import Dashboard from './components/Dashboard'
import Library from './components/Library'
import DVDQueue from './components/DVDQueue'
import ConfigPanel from './components/ConfigPanel'
import Login from './components/Login'
import Setup from './components/Setup'

// API instance
export const api = axios.create({
  baseURL: '/api'
})

// Add auth token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Handle auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

function App() {
  const [auth, setAuth] = useState({
    isAuthenticated: false,
    isLoading: true,
    firstRun: false
  })

  useEffect(() => {
    checkStatus()
  }, [])

  const checkStatus = async () => {
    try {
      const response = await api.get('/status')
      setAuth({
        isAuthenticated: !!localStorage.getItem('token') && !response.data.first_run,
        isLoading: false,
        firstRun: response.data.first_run
      })
    } catch (error) {
      setAuth({
        isAuthenticated: false,
        isLoading: false,
        firstRun: false
      })
    }
  }

  const login = (token) => {
    localStorage.setItem('token', token)
    setAuth({ ...auth, isAuthenticated: true, firstRun: false })
  }

  const logout = () => {
    localStorage.removeItem('token')
    setAuth({ ...auth, isAuthenticated: false })
  }

  if (auth.isLoading) {
    return <div className="loading">Loading...</div>
  }

  return (
    <Router>
      <div className="app">
        {auth.firstRun ? (
          <Routes>
            <Route path="*" element={<Setup onComplete={checkStatus} />} />
          </Routes>
        ) : !auth.isAuthenticated ? (
          <Routes>
            <Route path="/login" element={<Login onLogin={login} />} />
            <Route path="*" element={<Navigate to="/login" />} />
          </Routes>
        ) : (
          <>
            <nav className="sidebar">
              <div className="logo">
                <h1>DVD Ripper</h1>
              </div>
              <ul className="nav-links">
                <li><Link to="/">Dashboard</Link></li>
                <li><Link to="/library">Library</Link></li>
                <li><Link to="/queue">Queue</Link></li>
                <li><Link to="/config">Settings</Link></li>
              </ul>
              <button className="logout-btn" onClick={logout}>Logout</button>
            </nav>
            <main className="main-content">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/library" element={<Library />} />
                <Route path="/queue" element={<DVDQueue />} />
                <Route path="/config" element={<ConfigPanel />} />
              </Routes>
            </main>
          </>
        )}
      </div>
    </Router>
  )
}

export default App
