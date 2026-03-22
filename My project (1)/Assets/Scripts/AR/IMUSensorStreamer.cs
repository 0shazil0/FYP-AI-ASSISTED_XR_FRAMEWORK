using System;
using System.Collections;
using System.Collections.Generic;
using NeuroGuideXR.Networking;
using UnityEngine;

namespace NeuroGuideXR.AR
{
    public sealed class IMUSensorStreamer : MonoBehaviour
    {
        [SerializeField, Range(0.05f, 1.0f)] private float sendIntervalSeconds = 0.12f;
        [SerializeField] private bool sendWhenDisconnected = false;

        private Coroutine _streamCoroutine;

        private void OnEnable()
        {
            Input.gyro.enabled = true;
            _streamCoroutine = StartCoroutine(StreamImuLoop());
        }

        private void OnDisable()
        {
            if (_streamCoroutine != null)
            {
                StopCoroutine(_streamCoroutine);
                _streamCoroutine = null;
            }
        }

        private IEnumerator StreamImuLoop()
        {
            while (enabled)
            {
                var ws = WebSocketManager.Instance;
                bool canSend = ws != null && (ws.IsConnected || sendWhenDisconnected);

                if (canSend && ws != null)
                {
                    Vector3 acceleration = Input.acceleration;
                    Vector3 gyroRate = Input.gyro.rotationRateUnbiased;
                    Quaternion attitude = Input.gyro.attitude;

                    var payload = new Dictionary<string, object>
                    {
                        ["type"] = "imu",
                        ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                        ["imu"] = new Dictionary<string, object>
                        {
                            ["accel"] = new[] { acceleration.x, acceleration.y, acceleration.z },
                            ["gyro"] = new[] { gyroRate.x, gyroRate.y, gyroRate.z },
                            ["attitude"] = new[] { attitude.x, attitude.y, attitude.z, attitude.w },
                            ["device_orientation"] = Input.deviceOrientation.ToString(),
                        }
                    };

                    _ = ws.SendJsonAsync(payload);
                }

                yield return new WaitForSeconds(sendIntervalSeconds);
            }
        }
    }
}
