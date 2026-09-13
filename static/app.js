const tg = window.Telegram.WebApp;
tg.expand();

async function fetchHosts() {
    try {
        const response = await fetch('/api/hosts');
        const hosts = await response.json();
        const container = document.getElementById('hosts-container');
        container.innerHTML = '';
        
        hosts.forEach(host => {
            container.innerHTML += `
                <div class="host-card">
                    <img src="${host.photo_url || 'https://via.placeholder.com/70'}" alt="Host">
                    <div>
                        <h3>${host.name} (${host.status})</h3>
                        <div class="pricing-tiers">
                            <button onclick="bookHost('${host._id}', 1, 50)">1 Min - ₹50</button>
                            <button onclick="bookHost('${host._id}', 5, 300)">5 Min - ₹300</button>
                            <button onclick="bookHost('${host._id}', 10, 500)">10 Min - ₹500</button>
                        </div>
                    </div>
                </div>
            `;
        });
    } catch (error) {
        console.error("Error fetching hosts:", error);
    }
}

function bookHost(hostId, minutes, price) {
    alert(`Booking host for ${minutes} mins at ₹${price}`);
}

fetchHosts();
