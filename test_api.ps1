$response = curl -s http://localhost:8002/api/v1/lifelong-thriving/life-arc?user_id=9 -ErrorAction SilentlyContinue
if($response) {
    $response | Out-File -FilePath "c:\temp\api_response.json" -Encoding UTF8
    Write-Host "API Response saved to c:\temp\api_response.json"
} else {
    Write-Host "API not responding" | Out-File -FilePath "c:\temp\api_status.txt"
}
