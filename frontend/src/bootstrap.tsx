import React from "react";
import { createRoot } from "react-dom/client";
import RemoteApp from "./RemoteApp";

createRoot(document.getElementById("root")!).render(<React.StrictMode><RemoteApp standalone /></React.StrictMode>);
