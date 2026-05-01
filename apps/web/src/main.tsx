import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./context/AuthContext";
import { TinPreviewProvider } from "./context/TinPreviewContext";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <TinPreviewProvider>
          <App />
        </TinPreviewProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
