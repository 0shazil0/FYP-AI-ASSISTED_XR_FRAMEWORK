using UnityEngine;
using Newtonsoft.Json;

public class AROverlayManager : MonoBehaviour
{
    [Header("Prefabs")]
    public GameObject arrowPrefab;
    public GameObject highlightPrefab;
    public GameObject ghostHandPrefab;

    private GameObject _currentOverlay;

    private void Start()
    {
        if (WebSocketManager.Instance != null)
        {
            WebSocketManager.Instance.OnMessageReceived += HandleGuidanceMessage;
        }
    }

    private void OnDestroy()
    {
        if (WebSocketManager.Instance != null)
        {
            WebSocketManager.Instance.OnMessageReceived -= HandleGuidanceMessage;
        }
    }

    private void HandleGuidanceMessage(string jsonMessage)
    {
        try
        {
            var data = JsonConvert.DeserializeObject<GuidanceData>(jsonMessage);
            if (data != null && data.type == "guidance")
            {
                Debug.Log($"Rendering guidance: {data.instruction_text}");
                RenderOverlay(data);
            }
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Failed to parse guidance message: {e.Message}");
        }
    }

    private void RenderOverlay(GuidanceData data)
    {
        if (_currentOverlay != null)
        {
            Destroy(_currentOverlay);
        }

        // Convert the simple float array to a Vector3 (assuming relative offset for MVP)
        Vector3 positionOffset = new Vector3(data.location_3d[0], data.location_3d[1], data.location_3d[2]);
        
        // In a real app, you would Raycast against AR Planes or AR Anchors.
        // For this mock, we position it relative to the main camera.
        Transform camTransform = Camera.main.transform;
        Vector3 worldPos = camTransform.position + camTransform.forward * positionOffset.z + camTransform.right * positionOffset.x + camTransform.up * positionOffset.y;

        GameObject prefabToInstantiate = null;

        switch (data.visual_type.ToLower())
        {
            case "arrow":
                prefabToInstantiate = arrowPrefab;
                break;
            case "highlight":
                prefabToInstantiate = highlightPrefab;
                break;
            case "gesture":
            case "ghost_hand":
                prefabToInstantiate = ghostHandPrefab;
                break;
            default:
                Debug.LogWarning($"Unknown visual type: {data.visual_type}. Defaulting to Highlight.");
                prefabToInstantiate = highlightPrefab;
                break;
        }

        if (prefabToInstantiate != null)
        {
            _currentOverlay = Instantiate(prefabToInstantiate, worldPos, Quaternion.identity);
            
            // Billboard effect: Make it look at the camera
            _currentOverlay.transform.LookAt(camTransform);
        }
        else
        {
            // Placeholder fallback if prefabs aren't assigned
            _currentOverlay = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            _currentOverlay.transform.position = worldPos;
            _currentOverlay.transform.localScale = Vector3.one * 0.1f;
            _currentOverlay.GetComponent<Renderer>().material.color = Color.red;
            Debug.LogWarning("Rendering fallback sphere. Please assign prefabs in AROverlayManager.");
        }
    }

    [System.Serializable]
    public class GuidanceData
    {
        public string type;
        public string task;
        public string instruction_text;
        public string visual_type;
        public float[] location_3d;
    }
}
