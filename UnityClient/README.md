# NeuroGuide XR: Unity AR Client Setup

The scripts inside `Assets/Scripts` form the core logic for the AR client described in Phase 1 of the Master Plan. Because Unity projects are best generated via the **Unity Hub** to ensure proper manifest and package resolution, please follow these instructions to integrate these scripts into a working project.

## Prerequisites
- **Unity 6 (LTS)** installed via Unity Hub
- An AR-capable mobile device (iOS/Android) 
- The Python FastAPI backend running locally (`uvicorn main:app --reload --host 0.0.0.0 --port 8000`)

## Project Initialization

1. **Create a new Project:**
   - Open Unity Hub.
   - Click **New project**.
   - Select the **AR Mobile** template (or 3D Core, but AR Mobile is easier).
   - Name it `UnityClient` and save it to `d:\FYP Assisted AI with XR\`. (You can overwrite the directory I made, or move my `Assets/Scripts` folder into your new project's valid `Assets` folder).

2. **Install Required Packages:**
   - Go to `Window > Package Manager`.
   - Ensure the following are installed:
     - `AR Foundation`
     - `Apple ARKit XR Plugin` (if iOS) or `Google ARCore XR Plugin` (if Android)
   - *Third-Party Requirement:* You need `Newtonsoft.Json`. Go to Package Manager, click the `+`, choose "Add package from git URL", and enter: `com.unity.nuget.newtonsoft-json`.

3. **Scene Setup:**
   - Open your main scene.
   - If not using the AR template, delete the Main Camera.
   - Right-click in the Hierarchy > `XR > AR Session`.
   - Right-click in the Hierarchy > `XR > AR Session Origin` (or XR Origin in Unity 6). This will create an AR Camera.

4. **Attach the Scripts:**
   - Create an Empty GameObject called `NeuroGuideManager`.
   - Drag and drop `WebSocketManager.cs` onto it. (Change the IP address in the script to your PC's local IP, e.g., `ws://192.168.1.10:8000/stream`, if testing on a true mobile device).
   - Drag and drop `AROverlayManager.cs` onto it. Assign a 3D Sphere/Arrow prefab to its "Arrow Prefab" slot in the inspector.
   - Select the `AR Camera` under the XR Origin. 
   - Drag and drop `ARCameraCapture.cs` onto the AR Camera. Assign the `AR Camera Manager` script (which should already be attached to the AR Camera) to its inspector slot.
   - Drag and drop `AttentionGate.cs` onto the AR Camera.

5. **Test the Flow:**
   - Build and Run the project onto your phone.
   - Make sure your FastAPI Python backend is running.
   - Keep your phone very still for 1 second (This triggers the `AttentionGate`).
   - Look at your Python terminal; you should see `Received message of type: frame`.
   - Your phone should receive the mock JSON back and render a 3D overlay `1 meter` in front of the camera.

## How to Build and Run on Your Phone (Android/Windows Workflow)

Since you are developing on Windows, the easiest path is building for **Android**. Follow these steps:

### Part 1: Prepare Your Android Phone
1. **Enable Developer Options:** Go to Settings -> About Phone -> tap "Build Number" 7 times.
2. **Enable USB Debugging:** Go to Settings -> System -> Developer Options -> toggle "USB Debugging" ON.
3. Connect your phone to your PC via a USB cable. If a prompt appears on the phone, allow the PC to access data/debug.

### Part 2: Unity Build Settings for Android
1. In Unity, go to **File > Build Settings**.
2. Select **Android** from the Platform list and click **Switch Platform** (this may take a few minutes if it's your first time).
3. If it says "No Android module loaded," open Unity Hub, find your Unity Version install, click the gear icon > Add Modules, and install "Android Build Support" (including SDK/NDK tools).
4. Click **Player Settings** (bottom left of the Build Settings window) and ensure the following:
   - Under `Other Settings`, uncheck "Auto Graphics API" and ensure **Vulkan** is removed (ARCore works best with **OpenGLES3**).
   - Set the `Minimum API Level` to **Android 8.0 (API level 26)** or higher (Required for ARCore).
   - Under `XR Plug-in Management` (bottom of the left sidebar), check the box for **ARCore**.

### Part 3: Deploying the App
1. With your phone plugged in, go back to **File > Build Settings**.
2. In the "Run Device" dropdown, select your connected phone. (If it's not listed, hit "Refresh").
3. Make sure you've added your main Scene to the "Scenes In Build" list (click "Add Open Scenes").
4. **CRITICAL:** Open `WebSocketManager.cs` in your scripts and change `ws://localhost:8000/stream` to your PC's IP address (e.g., `ws://192.168.1.15:8000/stream`). Both your phone and PC must be on the same Wi-Fi network.
5. Click **Build and Run**. Choose a folder to save the `.apk` file.
6. Unity will compile the app and automatically launch it on your phone!
