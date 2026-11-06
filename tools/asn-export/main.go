// Export effective MMDB leaves, including IPv6 aliases. Queries use the same
// maxminddb reader version and net.IP normalization as pinned mihomo.
package main

import (
	"crypto/sha256"
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"os"

	"github.com/oschwald/maxminddb-golang"
)

type record struct {
	ASN uint32 `maxminddb:"autonomous_system_number"`
}

func run() error {
	database := flag.String("database", "", "MMDB snapshot")
	selection := flag.String("asns", "", "JSON ASN numbers")
	queries := flag.String("queries", "", "JSON IP addresses; query rather than export")
	flag.Parse()
	data, err := os.ReadFile(*database)
	if err != nil {
		return err
	}
	reader, err := maxminddb.FromBytes(data)
	if err != nil {
		return err
	}
	defer reader.Close()
	encoder := json.NewEncoder(os.Stdout)
	if *queries != "" {
		input, err := os.ReadFile(*queries)
		if err != nil {
			return err
		}
		var addresses []string
		if err = json.Unmarshal(input, &addresses); err != nil {
			return err
		}
		answers := make(map[string]uint32, len(addresses))
		for _, address := range addresses {
			ip := net.ParseIP(address)
			if ip == nil {
				return fmt.Errorf("invalid IP %q", address)
			}
			var value record
			if err = reader.Lookup(ip, &value); err != nil {
				return err
			}
			answers[address] = value.ASN
		}
		return encoder.Encode(answers)
	}
	input, err := os.ReadFile(*selection)
	if err != nil {
		return err
	}
	var values []uint32
	if err = json.Unmarshal(input, &values); err != nil {
		return err
	}
	selected := make(map[uint32]bool, len(values))
	for _, value := range values {
		selected[value] = true
	}
	found := make(map[uint32]bool)
	networks := make([]string, 0)
	leaves := 0
	iterator := reader.Networks() // Never SkipAliasedNetworks: aliases are observable.
	for iterator.Next() {
		var value record
		network, err := iterator.Network(&value)
		if err != nil {
			return err
		}
		leaves++
		if !selected[value.ASN] {
			continue
		}
		found[value.ASN] = true
		networks = append(networks, network.String())
		// IPv4 queries start at the ::/96 subtree; keep its IPv6 meaning
		// as well. A database need not also expose an ::ffff alias.
		if len(network.IP) == net.IPv6len {
			zero := true
			for _, b := range network.IP[:12] {
				if b != 0 {
					zero = false
				}
			}
			prefix, _ := network.Mask.Size()
			if zero && prefix >= 96 {
				networks = append(networks, (&net.IPNet{IP: network.IP[12:], Mask: net.CIDRMask(prefix-96, 32)}).String())
			}
		}
	}
	if err = iterator.Err(); err != nil {
		return err
	}
	missing := make([]uint32, 0)
	for _, value := range values {
		if !found[value] {
			missing = append(missing, value)
		}
	}
	return encoder.Encode(struct {
		Networks []string `json:"networks"`
		Missing  []uint32 `json:"missing_asns"`
		Leaves   int      `json:"database_leaves"`
		Type     string   `json:"database_type"`
		Epoch    uint     `json:"build_epoch"`
		SHA      string   `json:"sha256"`
	}{networks, missing, leaves, reader.Metadata.DatabaseType, reader.Metadata.BuildEpoch, fmt.Sprintf("%x", sha256.Sum256(data))})
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
